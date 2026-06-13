# Ported from vcm (ssm-report tooling) 2026-0119-tc2/py/vcm/v2/stat.py — Phase 1 engine/library tier.
# stat.json.xz -> tabs/csv/html (still shells hidb5-stat; Phase 2 will wire to ae.report.stat). See py/ae/report/MIGRATION.md.
import sys
from pathlib import Path
import datetime
import collections
import re
import csv
import json
import subprocess
import lzma
from ae.utils.time_series import TimeSeriesRange

# ======================================================================

from .dirs import lab_title

sVirusTypeForFilename = {"all": "all", "a(h3n2)": "h3n2", "a(h1n1)": "h1n1pdm", "h1seas": "h1n1seas", "h7": "h7", "h5": "h5", "b": "b", "victoria": "vic", "yamagata": "yam", "bvictoria": "bvic", "byamagata": "byam", "": ""}
sContinents = ["ASIA", "AUSTRALIA-OCEANIA", "NORTH-AMERICA", "EUROPE", "RUSSIA", "AFRICA", "MIDDLE-EAST", "SOUTH-AMERICA", "CENTRAL-AMERICA"]
# sLabOrder = ["CDC", "NIMR", "NIID", "MELB"]
sLabOrder = ["CDC", "CNIC", "Crick", "NIID", "VIDRL"]

sContinentsForTables = sContinents + ['all', 'sera', 'sera_unique']

sHeader = {'ASIA': 'Asia', 'AUSTRALIA-OCEANIA': 'Oceania', 'NORTH-AMERICA': 'N America ', 'EUROPE': 'Europe', 'RUSSIA': 'Russia', 'AFRICA': 'Africa',
           'MIDDLE-EAST': 'M East', 'SOUTH-AMERICA': 'S America', 'CENTRAL-AMERICA': 'C America', 'all': 'TOTAL', 'month': 'Year-Mo', 'year': 'Year',
           'sera': 'Sera', 'sera_unique': 'Sr Unique'}

sPeriodForFilename = {'year': '-year', 'month': ''}

sVirusTypeOrder = ['all', 'A(H1N1)', 'A(H3N2)', 'B', 'BVICTORIA', 'BYAMAGATA']

# ----------------------------------------------------------------------

def make_stat(output_dir: Path, hidb_dir: Path, time_series: TimeSeriesRange, previous_stat_dir: Path, make_all_names: bool = False, make_tabs: bool = True, make_csv: bool = True, make_webpage: bool = True):
    print(f">>> Updating stat in {output_dir} start={time_series.front_YMD()} end={time_series.back_YMD()}", file=sys.stderr)
    stat = _compute_stat(output_dir=output_dir, hidb_dir=hidb_dir, time_series=time_series)
    previous_stat = _load_previous_stat(previous_stat_dir=previous_stat_dir)
    if make_tabs:
        _make_tabs(output_dir, stat, previous_stat)
    if make_csv:
        _make_csv(output_dir, stat)
    if make_webpage:
        _make_webpage(output_dir, stat)

# ----------------------------------------------------------------------

def _compute_stat(output_dir, hidb_dir, time_series: TimeSeriesRange):
    output_dir.mkdir(exist_ok=True)
    output = output_dir.joinpath("stat.json.xz")
    subprocess.check_call(f"hidb5-stat --start '{time_series.front_YMD()}' --end '{time_series.after_last_YMD()}' --db-dir '{hidb_dir}' '{output}'", shell=True)
    return json.load(lzma.LZMAFile(output, "rb"))

# ----------------------------------------------------------------------

def _load_previous_stat(previous_stat_dir):
    previous_stat_path = previous_stat_dir and previous_stat_dir.joinpath('stat.json.xz')
    if previous_stat_path and previous_stat_path.exists():
        print(f">>> Loading previous stat from {previous_stat_path}", file=sys.stderr)
        previous_stat = json.load(lzma.LZMAFile(previous_stat_path, "rb"))
    else:
        previous_stat = None
    return previous_stat

# ----------------------------------------------------------------------

def _make_tabs(output_dir, stat, previous_stat):
    for virus_type in stat['antigens']:
        if virus_type != "BUNKNOWN":
            for lab in stat['antigens'][virus_type]:
                for period in ('month', 'year'):
                    _make_tab(output_dir=output_dir, output_suffix='.txt', stat=stat, previous_stat=previous_stat, virus_type=virus_type, lab=lab, period=period, make_header=_make_header_tab, make_line=_make_line_tab, make_separator=_make_separator_tab, make_footer=_make_footer_tab)

# ======================================================================

def _make_tab(output_dir, output_suffix, stat, previous_stat, virus_type, lab, period, make_header, make_line, make_separator, make_footer):
    data_antigens = stat['antigens'][virus_type][lab]
    data_sera_unique = stat['sera_unique'].get(virus_type, {}).get(lab, {})
    data_sera = stat['sera'].get(virus_type, {}).get(lab, {})
    if previous_stat:
        previous_vt = _fix_virus_type_for_previous(virus_type, previous_stat)
        previous_data_antigens = previous_stat['antigens'][previous_vt][lab]
        previous_data_sera_unique = previous_stat['sera_unique'].get(previous_vt, {}).get(lab, {})
        previous_data_sera = previous_stat['sera'].get(previous_vt, {}).get(lab, {})
    else:
        previous_data_antigens, previous_data_sera_unique, previous_data_sera = {}, {}, {}
    filename = Path(output_dir, '{lab}-{virus_type}{period}-tab{output_suffix}'.format(virus_type=sVirusTypeForFilename[virus_type.lower()], lab=lab.lower(), period=sPeriodForFilename[period], output_suffix=output_suffix))
    print(f">>> Writing {filename}", file=sys.stderr)
    with filename.open('w') as output:
        output.write(make_header(period))
        previous_sum = collections.defaultdict(int)
        has_previous = bool(previous_stat)
        for date in make_dates(data_antigens, period):
            output.write(make_line(date, data_antigens=data_antigens[date], data_sera=data_sera.get(date, {}), data_sera_unique=data_sera_unique.get(date, {}), period=period, has_previous=has_previous, previous_data_antigens=previous_data_antigens.get(date, {}), previous_data_sera=previous_data_sera.get(date, {}).get('all', 0), previous_data_sera_unique=previous_data_sera_unique.get(date, {}).get('all', 0)))
            if has_previous:
                for continent in sContinentsForTables[:-2]:
                    previous_sum[continent] += previous_data_antigens.get(date, {}).get(continent, 0)
                previous_sum['sera'] += previous_data_sera.get(date, {}).get('all', 0)
                previous_sum['sera_unique'] += previous_data_sera_unique.get(date, {}).get('all', 0)
        output.write(make_separator(solid=False, eol='\n'))
        output.write(make_line('all', data_antigens=data_antigens['all'], data_sera=data_sera.get('all', {}), data_sera_unique=data_sera_unique.get('all', {}), period=period, has_previous=has_previous, previous_data_antigens=previous_sum, previous_data_sera=previous_sum['sera'], previous_data_sera_unique=previous_sum['sera_unique']))
        output.write(make_separator(solid=True, eol='\n'))
        output.write(make_footer())

# ----------------------------------------------------------------------

def _make_header_tab(period):
    return '\n'.join((_make_separator_tab(solid=True, eol=''), _make_continent_names(period), _make_separator_tab(solid=False, eol=''), ''))

# ----------------------------------------------------------------------

def _make_line_tab(date, data_antigens, data_sera, data_sera_unique, period, has_previous, previous_data_antigens, previous_data_sera, previous_data_sera_unique):

    def diff_current_previous(continent):
        diff = data_antigens.get(continent, 0) - previous_data_antigens.get(continent, 0)
        if diff < 0:
            print(f"> {_format_date(date, period)} {continent}: Current: {data_antigens.get(continent, 0)} Previous: {previous_data_antigens.get(continent, 0)}", file=sys.stderr)
            diff = 0
        return diff

    if has_previous:
        if date == 'all':
            return ' '.join([_format_date(date, period)] + ['{:4d} ({:3d})'.format(data_antigens.get(continent, 0), diff_current_previous(continent)) for continent in sContinentsForTables[:-3]] + ['{:4d}({:4d})'.format(data_antigens.get('all', 0), data_antigens.get('all', 0) - previous_data_antigens.get('all', 0)), '{:4d} ({:3d})'.format(data_sera.get('all', 0), data_sera.get('all', 0) - previous_data_sera), '{:4d} ({:3d})'.format(data_sera_unique.get('all', 0), data_sera_unique.get('all', 0) - previous_data_sera_unique)]) + '\n'
        else:
            return ' '.join([_format_date(date, period)] + ['{:4d} ({:3d})'.format(data_antigens.get(continent, 0), diff_current_previous(continent)) for continent in sContinentsForTables[:-2]] + ['{:4d} ({:3d})'.format(data_sera.get('all', 0), data_sera.get('all', 0) - previous_data_sera), '{:4d} ({:3d})'.format(data_sera_unique.get('all', 0), data_sera_unique.get('all', 0) - previous_data_sera_unique)]) + '\n'
    else:
        return ' '.join([_format_date(date, period)] + ['{:10d}'.format(data_antigens.get(continent, 0)) for continent in sContinentsForTables[:-2]] + ['{:10d}'.format(data_sera.get('all', 0)), '{:10d}'.format(data_sera_unique.get('all', 0))]) + '\n'

# ----------------------------------------------------------------------

def _make_continent_names(period):
    return '{:<10s} {}'.format(period, ' '.join('{:>10s}'.format(n) for n in (sHeader[nn] for nn in sContinentsForTables)))

# ----------------------------------------------------------------------

def _make_separator_tab(solid, eol):
    if solid:
        s = '{}{}'.format('-' * 143, eol)
    else:
        s = ' '.join((' '.join('----------' for i in range(10)), '-----------', ' ----------', '---------')) + eol
    return s

# ----------------------------------------------------------------------

def _make_footer_tab():
    return ''

# ======================================================================

def _make_csv(output_dir, stat):
    stat = stat['antigens']
    months = [m for m in sorted(stat['all']['all']) if re.match(r'^[12]\d\d\d[01]\d$', m)]
    start, end = months[0], months[-1]
    years = ['{:04d}'.format(y) for y in range(int(months[0][:4]), int(months[-1][:4]) + 1)]
    virus_types = [v for v in sorted(stat) if v != 'B']
    virus_types_s = [v.replace('BVICTORIA', 'BVic').replace('BYAMAGATA', 'BYam').replace('all', 'Total') for v in virus_types]
    labs = sorted(stat['all'])
    labs_s = [lab.replace('all', 'Total') for lab in labs]
    filename = Path(output_dir, 'stat.csv')  # '{}-{}.csv'.format(start, end))
    print(f">>> Writing {filename}", file=sys.stderr)
    with filename.open('w') as fd:
        f = csv.writer(fd)
        _make_csv_tab(f=f, stat=stat, title='TOTAL {}-{}'.format(start, end), year='all', labs=labs, labs_s=labs_s, virus_types=virus_types, virus_types_s=virus_types_s, empty_row=False)
        for year in years:
            _make_csv_tab(f=f, stat=stat, title=year, year=year, labs=labs, labs_s=labs_s, virus_types=virus_types, virus_types_s=virus_types_s, empty_row=True)

# ----------------------------------------------------------------------

def _make_csv_tab(f, stat, title, year, labs, labs_s, virus_types, virus_types_s, empty_row):
    if empty_row:
        f.writerow([''])
    f.writerow([title])
    f.writerow([''] + virus_types_s)
    for lab_no, lab in enumerate(labs):
        values = [stat[virus_type][lab].get(year, {}).get('all', "") for virus_type in virus_types]
        f.writerow([labs_s[lab_no]] + [str(v) for v in values])

# ======================================================================

def _make_webpage(output_dir, stat):
    filename = Path(output_dir, 'index.html')
    print(f">>> Writing {filename}", file=sys.stderr)
    content = {
        'last_update': str(datetime.datetime.now()),
    }
    with filename.open('w') as output:
        output.write('<html>\n<head>\n<meta charset="utf-8"><title>Statistics for antigens and sera found in WHO CC HI tables</title>\n')
        output.write('<style type="text/css">\n<!--\n.flu-type { color: #008000; }\np.end-of-table { margin-bottom: 2em; }\n.table-in-plain-text { text-align: right; }\ntable.month td, table.year td {border: 1px solid #A0A0A0; }\ntd.number { text-align: right; padding: 0 1.5em 0 0; width: 3em; }\ntr.odd { background-color: #E0E0FF; } tr.even { background-color: white; }\nthead, tr.total { font-weight: bold; background-color: #F0E0E0; }\nthead { text-align: center; }\n\n-->\n</style></head>\n')
        output.write('<body><h1>Statistics for antigens and sera found in WHO CC HI tables</h1>\n<p style="font-size: 0.7em; text-align: right">Last update: {last_update}</p>\n'.format(**content))
        output.write('<ul style="margin: 1em;">\n')
        for virus_type in sVirusTypeOrder:
            output.write('<li><span class="flu-type" style="font-weight: bold;">{virus_type}</span> {links}</li>\n'.format(
                virus_type=virus_type.replace('all', 'All flu types,'), links=' '.join(f'<a href="#{virus_type}-{lab}">{lab_title(lab)}</a>' for lab in ['all'] + sLabOrder)))
        output.write('</ul>\n')
        output.write('<a href="stat.csv">Yearly statistics in the CSV format</a>\n')
        for virus_type in sVirusTypeOrder:
            output.write('<hr />\n<h2 id="{virus_type}" style="margin-bottom: 1em;"><span class="flu-type">{virus_type}</span></h2>\n'.format(virus_type=virus_type.replace('all', 'All flu types')))
            for lab in ['all'] + sLabOrder:
                # output.write('<hr />\n<h3 id="{virus_type}-{lab}" style="margin-bottom: 5px;"><span class="flu-type">{virus_type}</span> {lab}</h3>\n'.format(virus_type=virus_type.replace('all', 'All flu types,'), lab=lab_title(lab)))
                output.write(f'<h3 id="{virus_type}-{lab}" style="margin-bottom: 1em;">{lab_title(lab)} {virus_type.replace("all", "(All flu types)")}</h3>\n')
                _make_webtable(output=output, stat=stat, virus_type=virus_type, lab=lab, period='month')
                _make_webtable(output=output, stat=stat, virus_type=virus_type, lab=lab, period='year')
        output.write('<div style="margin-bottom: 2em;">></div>\n')
        output.write('</body>\n</html>\n')

# ----------------------------------------------------------------------

def _make_webtable(output, stat, virus_type, lab, period):
    data_antigens = stat['antigens'].get(virus_type, {}).get(lab, {})
    if data_antigens:
        data_sera_unique = stat['sera_unique'].get(virus_type, {}).get(lab, {})
        data_sera = stat['sera'].get(virus_type, {}).get(lab, {})

        def make_total():
            output.write('<tr class="total"><td class="date">TOTAL</td><td class="number">{continents}</td><td class="number">{serum}</td><td class="number">{serum_unique}</td></tr>\n'.format(continents='</td><td class="number">'.join(str(data_antigens['all'].get(continent, '')) for continent in sContinentsForTables[:-2]), serum=str(data_sera.get('all', {}).get('all', '')), serum_unique=str(data_sera_unique.get('all', {}).get('all', ''))))

        output.write('<table class="{period}" style="border: 1px solid #A0A0A0; border-collapse: collapse;">\n')
        output.write('<caption class="table-in-plain-text"><a href="{lab}-{virus_type}{period}-tab.txt">Table in plain text</a></caption>\n'.format(virus_type=sVirusTypeForFilename[virus_type.lower()], lab=lab.lower(), period=sPeriodForFilename[period]))
        output.write('<caption class="table-in-plain-text" style="caption-side:bottom;"><a href="{lab}-{virus_type}{period}-tab.txt">Table in plain text</a></caption>\n'.format(virus_type=sVirusTypeForFilename[virus_type.lower()], lab=lab.lower(), period=sPeriodForFilename[period]))
        output.write('<thead><td>{period}</td><td>{continents}</td></thead>\n'.format(period=period, continents='</td><td>'.join(sHeader[nn] for nn in sContinentsForTables)))
        output.write('<tbody>\n')
        make_total()
        for no, date in enumerate(make_dates(data_antigens, period, reverse=True)):
            output.write('<tr class="{odd_even}"><td class="date">{date}</td><td class="number">{continents}</td><td class="number">{serum}</td><td class="number">{serum_unique}</td></tr>\n'.format(odd_even="odd" if (no % 2) else "even", date=_format_date(date, period), continents='</td><td class="number">'.join(str(data_antigens[date].get(continent, '')) for continent in sContinentsForTables[:-2]), serum=str(data_sera.get(date, {}).get('all', '')), serum_unique=str(data_sera_unique.get(date, {}).get('all', ''))))
        output.write('\n')
        make_total()
        output.write('</tbody>\n')
        output.write('</table>\n')
        output.write('<p class="end-of-table" />\n')

# ======================================================================

sReYearMonth = {'month': re.compile(r'^\d{6}$', re.I), 'year': re.compile(r'^\d{4}$', re.I)}

def make_dates(data, period, **sorting):
    rex = sReYearMonth[period]
    return sorted((date for date in data if rex.match(date)), **sorting)

# ----------------------------------------------------------------------

def _format_date(date, period):
    if date[0] == '9':
        result = 'Unknown   '
    elif date == 'all':
        result = 'TOTAL     '
    elif len(date) == 4 or date[4:] == '99':
        if period == 'month':
            result = '{}-??   '.format(date[:4])
        else:
            result = '{}      '.format(date[:4])
    else:
        result = '{}-{}   '.format(date[:4], date[4:])
    return result

# ----------------------------------------------------------------------

def _fix_virus_type_for_previous(virus_type, previous_stat):
    if virus_type not in previous_stat['antigens']:
        if virus_type == "A(H3N2)":
            virus_type = "H3"
        elif virus_type == "A(H1N1)":
            virus_type = "H1PDM"
    return virus_type

# ======================================================================
