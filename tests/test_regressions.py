import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import ebay_aspects
import ebay_media
import local_listener
import work_pipeline
from listing_automation import clean, export_ebay_seller_hub_drafts
from ebay_draft_uploader import read_draft_csv, validate_csv, upload_drafts


class RegressionTests(unittest.TestCase):
    def test_compatibility_fields_keep_their_meaning(self):
        aspects = [{'name': name, 'required': False, 'usage': 'OPTIONAL',
                    'mode': 'FREE_TEXT'} for name in ('Compatible Brand', 'Compatible Model')]
        record = {'item_specifics': {}, 'missing_information': [], 'suggested_category': ''}
        result = ebay_aspects.complete_aspects(record, {'compatible_models': 'LaserJet M404'},
                                               {'category_id': '123', 'aspects': aspects})
        self.assertEqual(result['item_specifics']['Compatible Brand'], 'Not specified')
        self.assertEqual(result['item_specifics']['Compatible Model'], 'LaserJet M404')

    def test_listener_retry_requires_explicit_option(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'part.json'
            path.write_text('{}')
            state = {'part': {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'status': 'ERROR'}}
            with patch.object(local_listener, 'INPUT', Path(td)), \
                 patch.object(local_listener, 'save_state'), \
                 patch.object(local_listener, 'run_pipeline', return_value=0) as run:
                local_listener.process(state, False)
                run.assert_not_called()
                local_listener.process(state, False, retry_errors=True)
                run.assert_called_once_with('part', submit=False)
                self.assertEqual(state['part']['status'], 'PREVIEW_READY')

    def test_expired_photo_is_replaced_and_cache_saved(self):
        with tempfile.TemporaryDirectory() as td:
            photo = Path(td) / 'a.jpg'; photo.write_bytes(b'image')
            cache = Path(td) / 'cache.json'
            digest = hashlib.sha256(photo.read_bytes()).hexdigest()
            cache.write_text(json.dumps({digest: {'url': 'https://old'}}))
            with patch.object(ebay_media, 'cached_image_available', return_value=False), \
                 patch.object(ebay_media, 'upload_one', return_value='https://new') as upload:
                self.assertEqual(ebay_media.upload_images([photo], cache, 'token'), ['https://new'])
                upload.assert_called_once()
                self.assertEqual(json.loads(cache.read_text())[digest]['url'], 'https://new')

    def test_photo_network_failure_does_not_reupload(self):
        with patch.object(ebay_media, 'urlopen', side_effect=URLError('offline')):
            with self.assertRaises(RuntimeError):
                ebay_media.cached_image_available('https://example.com/image.jpg')
        with patch.object(ebay_media, 'urlopen', side_effect=HTTPError('https://example.com', 410, '', {}, None)):
            self.assertFalse(ebay_media.cached_image_available('https://example.com/image.jpg'))

    def test_saved_preview_corrections_survive_submission(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); photo = root / 'a.jpg'; photo.touch()
            folder = root / 'listing_drafts/work/part'; folder.mkdir(parents=True)
            record = clean({'title': 'Seller corrected title', 'item_specifics': {'Brand': 'Confirmed'}}, 'part', [photo])
            record.update(ebay_category_id='123', seller_details={'condition': 'used'})
            preview = folder / 'part.json'; preview.write_text(json.dumps(record))
            original = preview.read_bytes()
            pack = ('part', {}, {'title': 'Old research title'}, [photo], '123', [], {})
            with patch.object(work_pipeline, 'ROOT', root), \
                 patch.object(work_pipeline, 'package_data', return_value=pack), \
                 patch.object(work_pipeline, 'review_page'), \
                 patch('ebay_draft_uploader.seller_token', return_value='token'), \
                 patch('ebay_media.upload_images', return_value=['https://image']), \
                 patch('ebay_draft_uploader.upload_drafts', return_value={
                     'task_id': 'task1', 'status': 'COMPLETED',
                     'upload_summary': {'successCount': 1, 'failureCount': 0}}), \
                 patch('sys.argv', ['work_pipeline.py', 'part', '--submit']):
                self.assertEqual(work_pipeline.main(), 0)
            rows, _ = read_draft_csv(folder / 'ebay_seller_hub_drafts.csv')
            self.assertEqual(rows[0]['Title'], 'Seller corrected title')
            self.assertEqual(rows[0]['Condition ID'], 'USED')
            self.assertEqual(preview.read_bytes(), original)

    def test_export_and_duplicate_protection(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            record = {'id': 'part', 'title': 'A part', 'ebay_category_id': '123',
                      'seller_details': {'condition': 'new', 'quantity': 2}}
            export_ebay_seller_hub_drafts([record], folder)
            csv_path = folder / 'ebay_seller_hub_drafts.csv'
            self.assertEqual(validate_csv(csv_path), 1)
            rows, _ = read_draft_csv(csv_path)
            self.assertEqual(rows[0]['Condition ID'], 'NEW')
            self.assertIn('Price', rows[0])
            state = {'submissions': {'different-digest': {'skus': ['part']}}}
            (folder / 'ebay_feed_upload_state.json').write_text(json.dumps(state))
            with patch('ebay_draft_uploader.seller_token') as auth:
                with self.assertRaisesRegex(RuntimeError, 'Duplicate-draft protection'):
                    upload_drafts(csv_path, folder)
                auth.assert_not_called()


if __name__ == '__main__':
    unittest.main()
