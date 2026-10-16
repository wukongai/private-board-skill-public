"""Distribution checks; these do not measure real meeting utility."""
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET = re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{24,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----")
LOCAL = re.compile(r"/(?:Users|home)/[^\s/]+|" + "/var/" + r"folders/|[A-Z]:\\Users\\")

def check(root):
    errors=[]
    for f in root.rglob('*'):
        rel=f.relative_to(root)
        if any(x in rel.parts for x in ('.git','__pycache__','dist')):
            continue
        if f.is_symlink():
            errors.append('symlink:'+str(rel));continue
        if not f.is_file():continue
        if any(x in rel.parts for x in ('vendor','.skill-engineering','candidates')):
            errors.append('excluded:'+str(rel))
        if f.suffix not in ('.md','.yaml','.py') and f.name not in ('LICENSE','.gitignore'):
            errors.append('unexpected:'+str(rel));continue
        text=f.read_text(encoding='utf-8')
        if LOCAL.search(text):errors.append('local-path:'+str(rel))
        if SECRET.search(text):errors.append('credential:'+str(rel))
        if f.suffix=='.md':
            for link in re.findall(r'\]\(([^)]+)\)',text):
                link=link.split('#')[0]
                if not link or '://' in link:continue
                target=(f.parent/link).resolve()
                if not target.is_relative_to(root.resolve()) or not target.exists():
                    errors.append('link:'+str(rel)+':'+link)
    return errors

class PublicBundle(unittest.TestCase):
    def test_shipped_files(self):self.assertEqual(check(ROOT),[])
    def fixture(self,name,body=''):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        r=Path(t.name);p=r/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(body);return r
    def test_missing_link(self):self.assertTrue(check(self.fixture('a.md','[missing](missing.md)')))
    def test_escape_link(self):self.assertTrue(check(self.fixture('a.md','[outside](../../outside.md)')))
    def test_private_dependency(self):self.assertTrue(check(self.fixture('vendor/notes.md')))
    def test_machine_path(self):self.assertTrue(check(self.fixture('a.md','/'+'Users'+'/person/private.txt')))
    def test_credential(self):self.assertTrue(check(self.fixture('a.md','gh'+'p_'+'x'*30)))
    def test_symlink(self):
        r=self.fixture('a.md');(r/'linked.md').symlink_to(r/'a.md');self.assertTrue(check(r))
    def test_portable_layout(self):
        self.assertTrue((ROOT/'skills/private-board/SKILL.md').is_file())
        self.assertTrue((ROOT/'skills/private-board/references/business-framework.md').is_file())
        self.assertFalse((ROOT/'skills/private-board/vendor').exists())

if __name__=='__main__':unittest.main()
