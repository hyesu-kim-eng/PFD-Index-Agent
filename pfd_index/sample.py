"""Entirely synthetic drawing and known-answer fixture; no company source material."""
from pathlib import Path
import fitz

from .domain import Project, Symbol, number_symbols
from .exporter import make_template


def create_demo(folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    pdf=folder/'synthetic_pfd.pdf';template=folder/'synthetic_template.xlsx'
    make_template(template)
    symbols=[]
    with fitz.open() as doc:
        for number in (1,2):
            page=doc.new_page(width=600,height=460)
            page.insert_text((35,35),f'SYNTHETIC PFD / TRAIN {number}',fontsize=17,color=(.07,.22,.31))
            page.insert_text((35,55),'Generated example. No real plant or engineering design.',fontsize=9)
            page.draw_line((60,200),(540,200),width=1.5)
            page.insert_text((75,190),'3/4"',fontsize=11,color=(.8,.1,.1))
            page.insert_text((75,218),f'STREAM F-{number}',fontsize=10)
            for kind,x in [('FIC',160),('FI',460)]:
                page.draw_circle((x,140),16,width=1)
                page.insert_text((x-10,143),kind,fontsize=9)
                page.draw_line((x,157),(x,200),dashes='[4 3]')
                symbols.append(Symbol(page=number,x=x,y=140,kind=kind,raw_text=kind,
                    confidence=1,size='3/4',size_unit='inch',size_evidence=f'Synthetic stream F-{number}: visible 3/4-inch label',reviewed=True))
            controller=symbols[-2]
            page.draw_line((177,140),(300,140),dashes='[4 3]')
            page.draw_line((300,140),(300,190),dashes='[4 3]')
            page.draw_polyline([(290,190),(310,210),(310,190),(290,210),(290,190)],color=(0,0,0))
            symbols.append(Symbol(page=number,x=300,y=200,kind='FV',category='valve',confidence=1,
                controller_id=controller.id,size='3/4',size_unit='inch',
                size_evidence=f'Synthetic stream F-{number}: same 3/4-inch segment',reviewed=True))
            kind='TI' if number==1 else 'PI'
            size='4' if number==1 else '3'
            page.draw_line((60,390),(540,390),width=1.5)
            page.insert_text((75,380),size+'"',fontsize=11,color=(.8,.1,.1))
            page.draw_circle((160,350),16)
            page.insert_text((151,353),kind,fontsize=9)
            page.draw_line((160,367),(160,390),dashes='[4 3]')
            symbols.append(Symbol(page=number,x=160,y=350,kind=kind,raw_text=kind,confidence=1,
                size=size,size_unit='inch',size_evidence=f'Synthetic lower line: visible {size}-inch label',reviewed=True))
        doc.save(pdf)
    number_symbols(symbols)
    project=Project(pdf=str(pdf.resolve()),template=str(template.resolve()),plant='SYNTHETIC ACK DEMO',unit='DEMO',selected_pages=[1,2],
                    symbols=symbols,extraction={'status':'known_answer_fixture','source':'synthetic; not AI extracted'})
    project.save(folder/'synthetic_project.json')
    return project
