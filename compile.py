#!/usr/bin/env python
import argparse
import subprocess
import os
from pathlib import Path
import tempfile
import shutil
import configparser
import datetime
import logging
import re
from collections import defaultdict

logger = logging.getLogger()
sh = logging.StreamHandler()
logger.addHandler(sh)

template_warning = 'Alternative templates found on search path - Trying first:\n\t{}'
type_warning = 'Alternative doctypes found on search path - Trying first:\n\t{}'
pagelabel_warning = 'Message: [Rerun to get /PageLabels entry] found in output, rerunning'
tablewidth_warning = 'Message: [Table widths have changed] found in output, rerunning'
waitinginput_error = '\n{}\n{}'.format('=' * 40, 'Was waiting for input, fix and retry')
waitinginput_suggestion = 'Likely to be waiting for a filename, check your templates, and if necessary link to a source directory with -f'

extra_files = ['types/digsig.sty']

def verifyFilePath(possibleFilePath):
    p = Path(possibleFilePath)
    if p.is_file():
        return p.resolve(), True
    return p, False


def validFilePath(possibleFilePath):
    filepath, fileexists = verifyFilePath(possibleFilePath)
    if not fileexists:
        try:
            # Create and remove to validate ability to create
            filepath.touch()
            filepath.unlink()
        except OSError:
            msg = 'File: {} cannot be found or created'.format(possibleFilePath)
            raise argparse.ArgumentTypeError(msg)
    return filepath


def gatherFiles(filedict, folder):
    for filename in folder.iterdir():
        filedict[filename.stem].append(filename)


def searchMatch(searchtype='template'):
    dirs = ['.', '~/.dodoc/', '/etc/dodoc/']
    scriptdir = Path(__file__).resolve().parent
    if scriptdir != Path('.').resolve():
        dirs.append(scriptdir)
    possibilities = defaultdict(list)
    for d in dirs:
        templatedir = Path(d).joinpath('types')
        typedir = Path(d).joinpath('templates')
        if templatedir.is_dir() and searchtype is 'template':
            gatherFiles(possibilities, templatedir.resolve())
        if typedir.is_dir() and searchtype is 'doctype':
            gatherFiles(possibilities, typedir.resolve())
    return dict(possibilities)


def validFilePathOrTemplate(possibleFilePath):
    filepath, fileexists = verifyFilePath(possibleFilePath)
    if fileexists:
        return filepath
    possible_templates = searchMatch(searchtype='template')
    try:
        matching = possible_templates[possibleFilePath]
        if len(matching) > 1:
            logger.warn(template_warning.format('\n\t'.join(map(str, matching))))
        return matching[0]
    except KeyError:
        msg = 'File or template: {} cannot be found'.format(possibleFilePath)
        raise argparse.ArgumentTypeError(msg)


def validFilePathOrDocument(possibleFilePath):
    filepath, fileexists = verifyFilePath(possibleFilePath)
    if fileexists:
        return filepath
    possible_docs = searchMatch(searchtype='doctype')
    try:
        matching = possible_docs[possibleFilePath]
        if len(matching) > 1:
            logger.warn(type_warning.format('\n\t'.join(map(str, matching))))
        return matching[0]
    except KeyError:
        msg = 'File or doctype: {} cannot be found'.format(possibleFilePath)
        raise argparse.ArgumentTypeError(msg)


def daymod(date):
    day = str(date.day)
    if day.endswith('1'):
        return day + 'st'
    if day.endswith('2'):
        return day + 'nd'
    if day.endswith('3'):
        return day + 'rd'
    return day + 'th'


def monthmod(date):
    return date.strftime('%B')


def yearmod(date):
    return str(date.year)


def auto_replacements(autodict):
    if 'date' in autodict:
        if autodict['date'] == 'auto':
            date = datetime.datetime.now()
            autodict['date'] = date.strftime('%x')
        else:
            try:
                date = datetime.datetime.strptime(autodict['date'], '%x')
            except ValueError:
                logger.critical('Unexpected value for date in config file')
                raise
    date_mods = {'day': daymod, 'month': monthmod, 'year': yearmod}
    for date_element, mod in date_mods.items():
        try:
            if autodict[date_element] == 'from_date':
                autodict[date_element] = mod(date)
        except KeyError:
            pass


def _get_section_or_create(config, sectionname):
    """Get a config section, or create and return empty section"""
    try:
        return config[sectionname]
    except KeyError:
        config.add_section(sectionname)
    return config[sectionname]


def replace(document, patternfile, generate=False):
    '''This modifies the document in place, make sure you are always working on a copy'''
    print(document)
    with document.open('r') as doc:
        contents = doc.read()
    config = configparser.ConfigParser()
    config.read(str(patternfile))
    replacements = _get_section_or_create(config, 'manual')
    autos = dict(_get_section_or_create(config, 'auto'))
    auto_replacements(autos)
    replacements.update(autos)
    # Translate to template key format (re.escaped versions!)
    replacements = {re.escape('{{{}}}'.format(k)): v for k, v in replacements.items()}
    pattern = re.compile('|'.join(replacements.keys()))
    try:
        contents = pattern.sub(lambda m: replacements[re.escape(m.group(0))], contents)
    except KeyError:
        pass
    matches = re.compile(r'{(.*?)}')
    unmatched = matches.findall(contents)
    if len(unmatched) > 0:
        if generate:
            logger.info('Generating new values for configuration:')
            for m in set(unmatched):
                print('What value should be used for ' + str(m))
                value = input('\t- ')
                config.set('manual', str(m), value)
            with open(str(patternfile), 'w') as configfile:
                config.write(configfile)
            replace(document, patternfile, generate=generate)
            return
        msgs = '\n'.join('\tUnmatched replacement - ' + str(m) for m in unmatched)
        logger.warn('WARNING: Unmatched replacement found in document: \n{}'.format(msgs))
    with document.open('w') as doc:
        doc.write(contents)


def modenv(folderlist):
    env = os.environ.copy()

    prevTEX = env['TEXINPUTS'].split(os.pathsep) if 'TEXINPUTS' in env else []
    recursive_folders = [f + '//' for f in folderlist]
    newTEX = os.pathsep.join(recursive_folders + prevTEX)
    env['TEXINPUTS'] = newTEX + ':'
    return env


def mod_file(sourcefile, ext, unique=True, generate_non_unique=True, cntr=1):
    """Try to modify sourcefile to have ext, if dest exists and dest must be
    unique, then either generate a unqie version with numbers appended or raise"""
    if cntr > 1:
        destfile = sourcefile.parent.joinpath(sourcefile.stem + str(cntr)).with_suffix(ext)
    else:
        destfile = sourcefile.with_suffix(ext)
    if destfile.is_file() and unique:
        if generate_non_unique:
            return mod_file(sourcefile, ext, unique=unique, generate_non_unique=generate_non_unique, cntr=cntr + 1)
        raise FileExistsError()
    return destfile


def _generate(temp_dir, my_env, template, document, attempts=5):
    dest_file = mod_file(document, '.tex')
    output_file = mod_file(dest_file, '.pdf')
    final_file = mod_file(document, '.pdf')
    currwd = os.getcwd()
    os.chdir(temp_dir)
    subprocess.check_call(['pandoc', '-f', 'markdown', '-t', 'latex',
                           '--template={}'.format(template),
                           '{}'.format(document), '-o', '{}'.format(dest_file)])

    for attempt in range(1, attempts + 1):
        logger.info('Attempt number {}'.format(attempt))
        proc = subprocess.Popen(['xelatex', '{}'.format(dest_file)], stdout=subprocess.PIPE,
                                universal_newlines=True, env=my_env)
        outs = ''
        try:
            outs, errs = proc.communicate(timeout=8)
            if proc.returncode is None:
                continue
        except subprocess.TimeoutExpired:
            proc.kill()
            output, error = proc.communicate()
            logger.error(output)
            logger.error(waitinginput_error)
            logger.error(waitinginput_suggestion)
            break
        if 'Rerun to get /PageLabels entry' in outs:
            logger.warn(pagelabel_warning)
            continue
        if 'Table widths have changed' in outs:
            logger.warn(tablewidth_warning)
            continue
        shutil.copy('{}'.format(output_file), str(Path(currwd).joinpath(final_file.name)))
        os.chdir(currwd)
        print('Successfully processed')
        break
    else:
        os.chdir(currwd)
        raise RuntimeError('Tried {} times - table problems'.format(attempts))


def compile(template=None, document=None, folders=[], **kwargs):
    '''Compile a document using the template'''
    with tempfile.TemporaryDirectory() as temp_dir:
        folders = [str(Path(f).resolve()) for f in folders]
        my_env = modenv(['.', str(template.parent), str(document.parent)] + folders)
        template = Path(shutil.copy(str(template), temp_dir))
        document = Path(shutil.copy(str(document), temp_dir))
        for efile in extra_files:
            print(os.getcwd())
            shutil.copy(efile, temp_dir)
        if kwargs['replace']:
            replace(document, kwargs['replace'], generate=kwargs['generate'])
        _generate(temp_dir, my_env, template, document)


def _list_type(output, searchresults):
    """for each key in searchresults, format output for key and val list"""
    for key, val in searchresults.items():
        output += '\t{}\n'.format(key)
        for v in val:
            output += '\t\t{}\n'.format(v)
    return output


def list_all():
    '''List every template and doctype we can find'''
    templates = searchMatch(searchtype='template')
    doctypes = searchMatch(searchtype='doctype')
    tempout = _list_type('TEMPLATES:\n', templates)
    docout = _list_type('DOCUMENTS:\n', doctypes)
    print('All accessible templates and doctypes\n{}{}'.format(tempout, docout))


def main():
    """The main entry point for the script"""
    parser = argparse.ArgumentParser('Compile a document')
    parser.add_argument('-t', '--template', type=validFilePathOrTemplate, help='A latex template to apply - either a path to file or prebuilt template', default='document')
    parser.add_argument('-d', '--document', type=validFilePathOrDocument, help='The document template to apply the template to - either a path to file or prebuilt document', default='document')
    parser.add_argument('-r', '--replace', type=validFilePath, help='A set of replacement patterns to apply to the document')
    parser.add_argument('-g', '--generate', action='store_true', help='Generate a replacement pattern config file for any unmatched patterns')
    parser.add_argument('-f', '--folders', help='A folder containing referenced files', action='append', default=[])
    parser.add_argument('--list', help='List all possible templates and doctypes we can find', action='store_true')
    args = parser.parse_args()
    if args.list:
        list_all()
        return
    compile(**vars(args))


if __name__ == '__main__':
    main()
