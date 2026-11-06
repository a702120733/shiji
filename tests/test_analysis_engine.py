"""Incomplete model evidence must never appear as a complete analysis."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'shiji'))
from analysis_engine import _decode


class AnalysisEvidenceTest(unittest.TestCase):
    def test_missing_image_stays_partial(self):
        with tempfile.TemporaryDirectory() as temp:
            review = {'note_id': 'abcdefabcdefabcdefabcdef', 'fingerprint': 'test',
                      'metadata': {'content': '一张红色示意图'},
                      'images': ['notes/id/media/picture.png'], 'videos': [],
                      'capture_status': 'complete', 'prepare_status': 'complete', 'limitations': []}
            result = {'category': '图形素材', 'subcategory': '', 'tags': [],
                      'summary': '红色示意 · 方形图案 · 设计素材', 'key_points': [], 'takeaways': [],
                      'limitations': [], 'text_evidence': '正文描述红色示意图',
                      'image_evidence': [], 'frame_evidence': [], 'transcript_evidence': []}
            analysis = _decode(result, review, Path(temp))
            self.assertEqual(analysis['coverage']['status'], 'partial')
            self.assertIn('尚未核对全部内容', analysis['limitations'][0])

    def test_unlisted_media_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            review = {'note_id': 'abcdefabcdefabcdefabcdef', 'fingerprint': 'test',
                      'metadata': {'content': '正文'}, 'images': [], 'videos': [],
                      'capture_status': 'complete', 'prepare_status': 'complete', 'limitations': []}
            result = {'category': '图形素材', 'subcategory': '', 'tags': [],
                      'summary': '图形素材 · 来源正文 · 待补信息', 'key_points': [], 'takeaways': [],
                      'limitations': [], 'text_evidence': '正文',
                      'image_evidence': [{'path': '../outside.png', 'observation': '不存在'}],
                      'frame_evidence': [], 'transcript_evidence': []}
            with self.assertRaises(ValueError):
                _decode(result, review, Path(temp))


if __name__ == '__main__':
    unittest.main()
