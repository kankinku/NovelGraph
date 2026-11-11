"""Approved, scoped character context for a future Teller episode (synthetic only)."""
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

from novelgraph.__main__ import import_candidates
from novelgraph.world_state import approve_and_apply, review_candidate
from novelgraph.context_query import query_context


class ContextQueryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="novelgraph-context-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.root.chmod(0o700)
        self.dbpath = self.root / 'novelgraph.sqlite'

    def stage(self, episode, claims, *, work='novel', approve=True):
        story = ''.join(f'{line}\n' for line, _, _ in claims)
        source = self.root / f'{work}-{episode}.txt'
        source.write_text(story, encoding='utf-8')
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        pos = 0
        candidate_rows = []
        for line, kind, payload in claims:
            candidate_rows.append({'kind':kind, 'payload':payload,
                'evidence':{'start':pos,'end':pos+len(line),'text':line}})
            pos += len(line) + 1
        candidate_file = self.root / f'{work}-{episode}.json'
        candidate_file.write_text(json.dumps({'schema_version':1,'work_id':work,
             'episode':episode,'source_sha256':digest,'candidates':candidate_rows},ensure_ascii=False),encoding='utf-8')
        import_candidates(self.root, source, candidate_file)
        if approve:
            with sqlite3.connect(self.dbpath) as db:
                ids = [row[0] for row in db.execute('SELECT candidate_id FROM candidates WHERE work_id=? AND episode=? ORDER BY evidence_start', (work,episode))]
                for cid,(_,kind,_) in zip(ids, claims):
                    review_candidate(db,cid,digest,story,'approve','human','synthetic review')
                    if kind=='state_change':
                        approve_and_apply(db,cid,digest,story)
        return digest

    def fixture(self):
        self.stage(1,[
            ('A는 계약 담당자다.', 'entity',{'entity_id':'a','entity_type':'person','name':'A'}),
            ('B는 기업이다.', 'entity',{'entity_id':'b','entity_type':'organization','name':'B'}),
            ('C는 다른 사람이다.', 'entity',{'entity_id':'c','entity_type':'person','name':'C'}),
            ('D라는 이름이 중복된다.', 'entity',{'entity_id':'d1','entity_type':'person','name':'D'}),
            ('또 다른 D가 등장한다.', 'entity',{'entity_id':'d2','entity_type':'person','name':'D'}),
            ('A가 기업 B의 협력자다.', 'relation',{'source_id':'a','target_id':'b','relation_type':'employer'}),
            ('A가 기업 B와 계약했다.', 'event',{'actor_id':'a','target_id':'b','event_type':'contract_signed'}),
            ('C는 A의 이웃이다.', 'relation',{'source_id':'c','target_id':'a','relation_type':'neighbor'}),
            ('A는 B의 직원이다.', 'state_change',{'event_type':'state_set','actor_id':'a',
                    'category':'relationship','item_id':'employer','value':'B의 직원','relation_status':'active'}),
        ])
        self.stage(2,[('A가 기업 B에서 퇴사했다.', 'state_change',{'event_type':'state_set','actor_id':'a',
                    'category':'relationship','item_id':'employer','value':'퇴사함','relation_status':'ended'})])
        self.stage(3,[('A가 B와 새 사업을 논의했다.', 'event',{'actor_id':'a','target_id':'b','event_type':'new_deal'})])

    def context(self,episode=1,subject='a',scope='relations',**kw):
        with sqlite3.connect(self.dbpath.as_uri()+'?mode=ro',uri=True) as db:
            return query_context(db,'novel',episode,subject,scope,**kw)

    def test_context_a_company_b_path(self):
        self.fixture()
        result = self.context(1,scope='relationships',field='employer',target='b')
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['subject_id'],'a')
        self.assertTrue(result['facts'])
        self.assertTrue(any(f['kind']=='current_state' for f in result['facts']))
        self.assertTrue(any(f['kind']=='relation' for f in result['facts']))
        self.assertTrue(all(f['certainty']=='approved' and f['source_sha256'] for f in result['facts']))
        self.assertNotIn('neighbor',str(result))
        self.assertNotIn('new_deal',str(result))
        self.assertFalse(result['truncated'])
        self.assertNotIn('A는 계약 담당자다.',str(result))

    def test_history_vs_current_and_future(self):
        self.fixture()
        one=self.context(1,scope='relationships',field='employer')
        two=self.context(2,scope='relationships',field='employer')
        self.assertTrue(any(f['current_or_historical']=='current' and f.get('value')=='B의 직원' for f in one['facts']))
        self.assertTrue(any(f.get('value')=='퇴사함' and f['current_or_historical']=='historical' for f in two['facts']))
        self.assertFalse(any(f.get('value')=='B의 직원' and f['current_or_historical']=='current' for f in two['facts']))
        self.assertNotIn('new_deal',str(two))

    def test_context_bounds_and_cursor(self):
        self.fixture()
        claims=[(f'A가 B에 제안했다 {i}.','event',{'event_type':f'proposal_{i}','actor_id':'a','target_id':'b'}) for i in range(35)]
        self.stage(4,claims)
        first=self.context(4,scope='events',max_facts=10)
        self.assertEqual(len(first['facts']),10)
        self.assertTrue(first['truncated'])
        self.assertTrue(first['next_cursor'])
        second=self.context(4,scope='events',max_facts=10,cursor=first['next_cursor'])
        self.assertFalse(set(f['candidate_id'] for f in first['facts']) & set(f['candidate_id'] for f in second['facts']))
        with self.assertRaisesRegex(ValueError,'cursor'):
            self.context(4,scope='relations',max_facts=10,cursor=first['next_cursor'])

    def test_identity_ambiguity_not_found_and_wrong_work(self):
        self.fixture()
        self.assertEqual(self.context(1,subject='D')['status'],'ambiguous')
        self.assertEqual(self.context(1,subject='unknown')['status'],'not_found')
        self.assertEqual(self.context(1,subject='A')['subject_id'],'a')
        with sqlite3.connect(self.dbpath.as_uri()+'?mode=ro',uri=True) as db:
            with self.assertRaises(ValueError):
                query_context(db,'other',1,'a','relations')

    def test_unapproved_and_read_only(self):
        self.fixture()
        self.stage(4,[('A가 C에게 비밀 약속을 했다.', 'relation',{'source_id':'a','target_id':'c','relation_type':'secret'})],approve=False)
        before=hashlib.sha256(self.dbpath.read_bytes()).hexdigest()
        result=self.context(4,scope='relations')
        self.assertNotIn('secret',str(result))
        self.assertEqual(before,hashlib.sha256(self.dbpath.read_bytes()).hexdigest())

    def test_cli_context_and_invalid_inputs(self):
        self.fixture()
        def invoke(*args):
            return subprocess.run([sys.executable,'-m','novelgraph','--data-root',str(self.root),
                  'query-context','--work-id','novel','--episode','1','--subject','A','--scope','relations',*args],
                  capture_output=True,text=True,timeout=30)
        good=invoke('--target','b')
        self.assertEqual(good.returncode,0,good.stderr)
        self.assertEqual(json.loads(good.stdout)['work_id'],'novel')
        for bad in [('--max-hops','99'),('--scope','SELECT *'),('--cursor','wrong')]:
            got=invoke(*bad)
            self.assertEqual(got.returncode,2,got.stdout+got.stderr)
        self.assertEqual(invoke('--subject','D').returncode,0)


if __name__=='__main__':
    unittest.main()
