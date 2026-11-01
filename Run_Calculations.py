"""Run an explicit calculation plan without the browser."""
import argparse
import json
from pathlib import Path
import sys
from calculation import run_pipeline, discover_machline


def main():
    p=argparse.ArgumentParser(description='Section Studio calculation series')
    p.add_argument('model',type=Path)
    p.add_argument('--plan',type=Path,required=True)
    p.add_argument('--vspscript',required=True)
    p.add_argument('--machline')
    p.add_argument('--units',choices=['ft','m','mm','in'],default='ft')
    p.add_argument('--output',type=Path,default=Path('Calculation_runs'))
    args=p.parse_args()
    try:
        r=run_pipeline(args.vspscript,args.machline or discover_machline(Path(__file__).parent),Path(__file__).parent,args.output,
            {'xml':args.model.read_text(encoding='utf-8'),'units':args.units,'plan':json.loads(args.plan.read_text(encoding='utf-8'))},
            lambda message,*a,**k:print(message,flush=True))
        print('Report:',args.output/r['report']['id']/'report.json')
        return 0 if r['report']['passed'] else (1 if r['report']['state']=='error' else 2)
    except (OSError,ValueError,RuntimeError,TimeoutError) as e:
        print(str(e),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
