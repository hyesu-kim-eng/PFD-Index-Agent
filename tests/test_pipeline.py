import copy
import io
import json
from pathlib import Path
import shutil
import uuid
import unittest

import fitz
import openpyxl

from pfd_index.domain import Project, Symbol, deduplicate, normalize_size, number_symbols, parse_pages, validate
from pfd_index.exporter import export_bundle, export_pdf, export_workbook, inspect_template, make_template
from pfd_index.sample import create_demo
from pfd_index.vision import VisionClient, extract, parse_response, symbols_from_result


class NumberingTests(unittest.TestCase):
    def test_pages_continue_and_valves_follow_controllers(self):
        a=Symbol(page=1,kind='FIC');b=Symbol(page=2,kind='FICQ')
        v=Symbol(page=1,kind='FV',category='valve',controller_id=a.id)
        w=Symbol(page=2,kind='FV',category='valve',controller_id=b.id)
        fi=Symbol(page=2,kind='FI')
        number_symbols([a,v,b,w,fi])
        self.assertEqual((a.tag,v.tag,b.tag,w.tag,fi.tag),('FIC-001','FV-001','FICQ-002','FV-002','FI-001'))

    def test_unlinked_valve_does_not_steal_linked_tag(self):
        a=Symbol(kind='FIC');b=Symbol(kind='FV',category='valve',controller_id=a.id)
        c=Symbol(kind='FV',category='valve')
        number_symbols([a,b,c]);self.assertEqual((b.tag,c.tag),('FV-001','FV-002'))

    def test_locked_edits_survive(self):
        a=Symbol(kind='FIC',tag='FIC-040',tag_locked=True)
        v=Symbol(kind='FV',tag='FV-040',tag_locked=True,category='valve',controller_id=a.id)
        b=Symbol(kind='FIC',page=2)
        number_symbols([a,v,b]);self.assertEqual(b.tag,'FIC-041')

    def test_multiple_valves_need_explicit_disambiguation(self):
        a=Symbol(kind='TIC')
        valves=[Symbol(kind='TV',category='valve',controller_id=a.id) for _ in range(2)]
        with self.assertRaises(ValueError):number_symbols([a]+valves)

    def test_invalid_link_not_silently_replaced(self):
        a=Symbol(kind='TI');v=Symbol(kind='TV',category='valve',controller_id=a.id)
        with self.assertRaises(ValueError):number_symbols([a,v])

    def test_duplicate_locked_tag_rejected(self):
        with self.assertRaises(ValueError):number_symbols([Symbol(tag='FI-001',tag_locked=True),Symbol(tag='FI-001',tag_locked=True)])

    def test_tile_overlap_dedup_but_adjacent_bubbles_remain(self):
        a=Symbol(x=10,y=10,kind='TI',confidence=.9)
        overlap=Symbol(x=11,y=11,kind='TI',confidence=.8)
        nearby=Symbol(x=20,y=10,kind='TI',confidence=.9)
        self.assertEqual(len(deduplicate([a,overlap,nearby])),2)

    def test_conflicting_glyphs_flagged(self):
        values=deduplicate([Symbol(kind='PQI',x=10,y=10,confidence=.9),Symbol(kind='PDI',x=10,y=10,confidence=.8)])
        self.assertEqual(len(values),1);self.assertLessEqual(values[0].confidence,.5)


class SizeTests(unittest.TestCase):
    def test_fraction_and_dual_sizes(self):
        for raw,expected in [('3/4','3/4B'),('1 1/2"','1 1/2B'),('6"/8"','6B/8B'),('6B/8B','6B/8B'),('4B','4B')]:
            with self.subTest(raw=raw):self.assertEqual(normalize_size(raw,'inch'),expected)

    def test_metric_never_becomes_nominal_inches(self):
        self.assertEqual(normalize_size('270Φ','mm'),'270Φ')
        self.assertEqual(normalize_size('80','mm'),'80Φ')
        self.assertEqual(normalize_size('','unknown'),'-')

    def test_invalid_size_fails(self):
        for text in ['three','3/0','?']:
            with self.subTest(text=text),self.assertRaises(ValueError):normalize_size(text,'inch')

    def test_page_range(self):
        self.assertEqual(parse_pages('1-3,5',9),[1,2,3,5])
        for text in ['0','3-2','1-10','a']:
            with self.subTest(text=text),self.assertRaises(ValueError):parse_pages(text,9)


class ProviderTests(unittest.TestCase):
    def test_refusal_and_incomplete_are_not_success(self):
        for data in [{'status':'incomplete'},{'status':'completed','output':[{'content':[{'type':'refusal'}]}]}, {'status':'completed','output':[]}]:
            with self.assertRaises(RuntimeError):parse_response(data)

    def test_request_uses_images_strict_schema_and_no_storage(self):
        observed={}
        def opener(request,timeout):
            observed.update(json.loads(request.data))
            return io.BytesIO(json.dumps({'status':'completed','output':[{'content':[{'type':'output_text','text':'{"symbols": []}'}]}]}).encode())
        client=VisionClient('test-only-placeholder',opener=opener)
        self.assertEqual(client.ask('system','input',[b'image'],{'type':'object'}),{'symbols':[]})
        self.assertFalse(observed['store']);self.assertTrue(observed['text']['format']['strict'])
        self.assertEqual(observed['input'][1]['content'][1]['type'],'input_image')

    def test_tile_coordinates_remap_to_pdf_points(self):
        data={'symbols':[{'x':500,'y':250,'kind':'TI','category':'instrument','raw_text':'TI','confidence':.9,
                         'size':'3/4','size_unit':'inch','size_evidence':'stream 4','notes':''}]}
        item=symbols_from_result(data,2,fitz.Rect(100,200,300,600))[0]
        self.assertEqual((item.x,item.y,item.page),(200,300,2))
        data['symbols'][0]['x']=1100
        with self.assertRaises(ValueError):symbols_from_result(data,2,fitz.Rect(100,200,300,600))


class ExportTests(unittest.TestCase):
    def setUp(self):
        base=Path(__file__).resolve().parent.parent/'local_data'/'test_runs'
        base.mkdir(parents=True,exist_ok=True)
        self.root=base/('case_'+uuid.uuid4().hex)
        self.root.mkdir()
        assert self.root.resolve().is_relative_to(base.resolve())
        self.project=create_demo(self.root/'sample')

    def tearDown(self):
        base=Path(__file__).resolve().parent.parent/'local_data'/'test_runs'
        assert self.root.resolve().is_relative_to(base.resolve())
        shutil.rmtree(self.root)

    def test_end_to_end_pdf_excel_exact_tag_and_page_match(self):
        folder=export_bundle(self.project,self.root/'out')
        sheet=openpyxl.load_workbook(folder/'Instrument_Index.xlsx').active
        tags={sheet.cell(i,5).value for i in range(3,sheet.max_row+1)}
        with fitz.open(folder/'PFD_Tagged.pdf') as pdf:
            annotations=[(i+1,a.info['content']) for i,p in enumerate(pdf) for a in p.annots() or []]
            self.assertEqual(tags,{t for _,t in annotations})
            self.assertEqual(len(annotations),len(tags))
            for i,p in enumerate(pdf):
                for a in p.annots() or []:
                    ap=int(pdf.xref_get_key(a.xref,'AP/N')[1].split()[0])
                    self.assertIn(b'1 0 0 RG',pdf.xref_stream(ap))
                    self.assertIn(a.info['content'].encode('ascii'),pdf.xref_stream(ap))
        for row in range(3,sheet.max_row+1):
            tag=sheet.cell(row,5).value
            item=next(s for s in self.project.symbols if s.tag==tag)
            self.assertEqual(sheet.cell(row,11).value,item.page)
            self.assertEqual(sheet.cell(row,12).value,normalize_size(item.size,item.size_unit))

    def test_unselected_page_remains_untagged(self):
        self.project.selected_pages=[1]
        self.project.symbols=[s for s in self.project.symbols if s.page==1]
        path=self.root/'one.pdf';export_pdf(self.project,path)
        with fitz.open(path) as doc:
            self.assertEqual(len(doc),2);self.assertEqual(list(doc[1].annots() or []),[])

    def test_user_template_description_and_styles_preserved(self):
        w=openpyxl.load_workbook(self.project.template);s=w.active
        s['E3']='FIC-789';s['J3']='Flow Transmitter - DP';s['B3']='USER PLANT';w.save(self.project.template)
        self.project.rules=inspect_template(self.project.template)['rules']
        path=self.root/'index.xlsx';export_workbook(self.project,path)
        result=openpyxl.load_workbook(path).active
        row=next(r for r in result.iter_rows(min_row=3) if r[4].value=='FIC-001')
        self.assertEqual(row[9].value,'Flow Transmitter - DP')
        self.assertEqual(result['J2'].fill.fgColor.rgb,s['J2'].fill.fgColor.rgb)
        self.assertEqual(openpyxl.load_workbook(self.project.template).active['E3'].value,'FIC-789')

    def test_conflicting_template_descriptions_not_learned(self):
        w=openpyxl.load_workbook(self.project.template);s=w.active
        s['E3']='AI-001';s['J3']='Ampere Indicator';s['E4']='AI-002';s['J4']='Analysis Indicator';w.save(self.project.template)
        self.assertNotIn('AI',inspect_template(self.project.template)['rules'])

    def test_duplicate_tags_block_export(self):
        self.project.symbols[1].tag=self.project.symbols[0].tag
        with self.assertRaises(ValueError):export_bundle(self.project,self.root/'bad')

    def test_project_roundtrip_does_not_store_api_key(self):
        path=self.root/'project.json';self.project.save(path)
        self.assertEqual(len(Project.load(path).symbols),8)
        self.assertNotIn('api_key',path.read_text())

    def test_warning_for_unverified_ai_and_missing_size(self):
        item=self.project.symbols[0];item.kind='AI';item.size='';item.size_unit='unknown';item.description=''
        messages=[i['message'] for i in validate(self.project)]
        self.assertTrue(any('구경' in m for m in messages));self.assertTrue(any('기능' in m for m in messages))

    def test_rotated_page_export_uses_display_coordinates(self):
        source=self.root/'rotated.pdf'
        with fitz.open() as doc:
            p=doc.new_page(width=400,height=600);p.set_rotation(90);doc.save(source)
        p=Project(pdf=str(source),template=self.project.template,selected_pages=[1],
                  symbols=[Symbol(page=1,x=480,y=200,kind='TI',tag='TI-001',size_unit='not_applicable',reviewed=True)])
        output=self.root/'rotated_tagged.pdf';export_pdf(p,output)
        with fitz.open(output) as doc:
            page=doc[0];a=next(page.annots());display=a.rect*page.rotation_matrix
            self.assertTrue(page.rect.contains(display))
            self.assertLess(abs(display.x0-480),100)
            self.assertIn(b'TI-001',doc.xref_stream(int(doc.xref_get_key(a.xref,'AP/N')[1].split()[0])))

    def test_mock_extraction_links_numbers_and_caches(self):
        class MockClient:
            model='mock-test'
            calls=0
            def ask(self,system,text,images,schema,cancel):
                self.calls+=1
                if 'links' in schema['properties']:
                    items=json.loads(text)['symbols_pdf_coordinates']
                    v=next(i for i in items if i['category']=='valve')
                    c=next(i for i in items if i['category']=='instrument')
                    return {'links':[{'valve_id':v['id'],'controller_id':c['id'],'confidence':.95,'evidence':'synthetic dashed signal'}]}
                fields={'raw_text':'','confidence':.95,'size':'3/4','size_unit':'inch','size_evidence':'synthetic stream label','notes':''}
                return {'symbols':[dict(fields,kind='FIC',category='instrument',x=250,y=300),
                                   dict(fields,kind='FV',category='valve',x=500,y=450)],'warnings':[]}
        p=Project(pdf=self.project.pdf,template=self.project.template,selected_pages=[1])
        client=MockClient();extract(p,client,self.root/'cache',detailed=False)
        self.assertEqual({s.tag for s in p.symbols},{'FIC-001','FV-001'})
        self.assertTrue(next(s for s in p.symbols if s.category=='valve').controller_id)
        self.assertEqual(client.calls,2)
        extract(p,client,self.root/'cache',detailed=False)
        self.assertEqual(client.calls,3) # cached extraction, newly reconciled links/IDs
        self.assertFalse([i for i in validate(p) if i['level']=='error'])

    def test_partial_analysis_does_not_look_like_a_complete_export(self):
        self.project.extraction={'model':'mock','completed_pages':[1]}
        with self.assertRaises(ValueError):export_bundle(self.project,self.root/'partial')


if __name__=='__main__':unittest.main()
