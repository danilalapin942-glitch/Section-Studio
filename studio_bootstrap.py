"""Windows-friendly entry point with persistent UTF-8 startup/error logs."""
from __future__ import annotations
import argparse,logging,logging.handlers,os,sys,tempfile,traceback
from pathlib import Path

class LoggedStream:
    def __init__(self,original,logger):self.original=original;self.logger=logger;self.pending=''
    @property
    def encoding(self):return getattr(self.original,'encoding','utf-8')
    def write(self,text):
        if self.original:
            try:self.original.write(text)
            except UnicodeError:self.original.write(text.encode(self.encoding or'utf-8',errors='replace').decode(self.encoding or'utf-8'))
        self.pending+=text
        while '\n'in self.pending:
            line,self.pending=self.pending.split('\n',1)
            if line:self.logger.info(line)
        return len(text)
    def flush(self):
        if self.pending:self.logger.info(self.pending);self.pending=''
        if self.original:self.original.flush()
    def isatty(self):return bool(self.original and self.original.isatty())
    def fileno(self):return self.original.fileno()

def main(argv=None):
    argv=list(sys.argv[1:]if argv is None else argv)
    parser=argparse.ArgumentParser(add_help=False);parser.add_argument('--config')
    known,_=parser.parse_known_args(argv)
    default=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.config')))/'SectionStudio'
    folder=Path(known.config).expanduser().resolve().parent if known.config else default
    try:
        folder.mkdir(parents=True,exist_ok=True);log_path=folder/'launch.log'
        handler=logging.handlers.RotatingFileHandler(log_path,maxBytes=2*1024*1024,backupCount=2,encoding='utf-8')
    except OSError as exc:
        folder=Path(tempfile.mkdtemp(prefix='SectionStudio_Startup_'));log_path=folder/'launch.log';handler=logging.FileHandler(log_path,encoding='utf-8')
        print('Cannot write settings/log folder:',str(exc));print('Temporary startup log:',log_path)
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    logger=logging.getLogger('section_studio_startup');logger.setLevel(logging.INFO);logger.handlers=[handler];logger.propagate=False
    stdout,stderr=sys.stdout,sys.stderr;sys.stdout=LoggedStream(stdout,logger);sys.stderr=LoggedStream(stderr,logger)
    try:
        print('Section Studio startup');print('Python:',sys.version.split()[0]);print('Folder:',Path(__file__).resolve().parent);print('Startup log:',log_path,flush=True)
        if sys.version_info<(3,10):raise RuntimeError('Python 3.10 or newer is required.')
        from section_studio_server import main as serve
        return serve(argv)
    except KeyboardInterrupt:return 0
    except SystemExit as exc:return int(exc.code or 0)if isinstance(exc.code,(int,type(None)))else 1
    except Exception:
        traceback.print_exc();print('Startup failed. See the error above and:',log_path,flush=True);return 1
    finally:
        sys.stdout.flush();sys.stderr.flush();sys.stdout,sys.stderr=stdout,stderr;handler.close();logger.handlers=[]

if __name__=='__main__':raise SystemExit(main())
