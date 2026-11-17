"""Launch the desktop tool, or use the repeatable CLI pipeline."""
import argparse
import os
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description='ACK Project Instrument Index Agent')
    parser.add_argument('--demo',action='store_true',help='Generate a synthetic known-answer project')
    parser.add_argument('--project',help='Load a reviewed project JSON')
    parser.add_argument('--analyze',metavar='PDF',help='Send selected PDF page images to the OpenAI API')
    parser.add_argument('--template',help='Existing Instrument Index workbook')
    parser.add_argument('--pages',default='1-5',help='Pages, e.g. 1-5 or 1,3,7')
    parser.add_argument('--model',default=os.environ.get('OPENAI_MODEL','gpt-6-astra'))
    parser.add_argument('--quick',action='store_true',help='One full-page image pass rather than four extra detail regions')
    parser.add_argument('--export',metavar='DIRECTORY',help='Write a PDF/XLSX/project/review bundle')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    if sum(bool(x) for x in (args.demo,args.project,args.analyze))>1:
        parser.error('Choose one of --demo, --project, --analyze.')
    if not any((args.demo,args.project,args.analyze)):
        from pfd_index.app import main as gui
        gui();return
    from pfd_index.domain import Project,parse_pages
    if args.demo:
        from pfd_index.sample import create_demo
        project=create_demo(root/'local_data'/'demo')
    elif args.project:project=Project.load(args.project)
    else:
        import fitz
        from pfd_index.vision import VisionClient,extract
        from pfd_index.exporter import inspect_template
        if not args.template:parser.error('--analyze requires --template.')
        data=inspect_template(args.template)
        with fitz.open(args.analyze) as doc:pages=parse_pages(args.pages,len(doc))
        project=Project(pdf=str(Path(args.analyze).resolve()),template=str(Path(args.template).resolve()),
                        selected_pages=pages,plant=data['plant'] or 'PLANT',unit=data['unit'] or 'UNIT',rules=data['rules'])
        client=VisionClient(os.environ.get('OPENAI_API_KEY',''),args.model)
        extract(project,client,root/'local_data'/'cache',not args.quick,print)
        project.save(root/'local_data'/'last_analysis.json')
    if args.export:
        from pfd_index.exporter import export_bundle
        print(export_bundle(project,args.export))
    else:print(f'{len(project.symbols)} symbols loaded. Add --export DIRECTORY or open the desktop app.')


if __name__=='__main__':main()
