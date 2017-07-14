#!/usr/bin/env python
import argparse
import subprocess
import os
import tempfile
import shutil
import configparser
import datetime
import re


def validFilePath(possibleFilePath):
    if os.path.isfile(possibleFilePath):
        return os.path.abspath(possibleFilePath)
    msg = 'File: {} cannot be found'.format(possibleFilePath)
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
                print('ERROR: Unexpected value for date in config file')
                raise
    date_mods = {'day': daymod, 'month': monthmod, 'year': yearmod}
    for date_element, mod in date_mods.items():
        if autodict[date_element] == 'from_date':
            autodict[date_element] = mod(date)


def replace(document, patternfile):
    '''This modifies the document in place, make sure you are always working on a copy'''
    with open(document, 'r') as doc:
        contents = doc.read()
    config = configparser.ConfigParser()
    config.read(patternfile)
    replacements = config['manual']
    auto_replacements(config['auto'])
    replacements.update(config['auto'])
    # Translate to template key format (re.escaped versions!)
    replacements = {re.escape('{{{}}}'.format(k)): v for k, v in replacements.items()}
    pattern = re.compile('|'.join(replacements.keys()))
    contents = pattern.sub(lambda m: replacements[re.escape(m.group(0))], contents)
    matches = re.compile(r'{(.*?)}')
    unmatched = matches.findall(contents)
    if len(unmatched) > 0:
        msgs = '\n'.join('\tUnmatched replacement - ' + str(m) for m in unmatched)
        print('WARNING: Unmatched replacement found in document: \n{}'.format(msgs))
    with open(document, 'w') as doc:
        doc.write(contents)


def modenv(folderlist):
    env = os.environ.copy()

    prevTEX = env['TEXINPUTS'].split(os.pathsep) if 'TEXINPUTS' in env else []
    newTEX = os.pathsep.join(folderlist + prevTEX)
    env['TEXINPUTS'] = newTEX
    return env


def _generate(temp_dir, my_env, template, document, attempts=5):
    base = os.path.splitext(os.path.basename(document))[0]
    currwd = os.getcwd()
    os.chdir(temp_dir)
    subprocess.check_call(['pandoc', '-f', 'markdown', '-t', 'latex',
                           '--template={}'.format(template),
                           '{}'.format(document), '-o' '{}.tex'.format(base)],
                          env=my_env)

    for attempt in range(1, attempts+1):
        print('Attempt number {}'.format(attempt))
        proc = subprocess.Popen(['xelatex', '{}.tex'.format(base)], stdout=subprocess.PIPE,
                                universal_newlines=True, env=my_env)
        outs = ''
        try:
            outs, errs = proc.communicate(timeout=5)
            if proc.returncode is None:
                continue
        except subprocess.TimeoutExpired:
            proc.kill()
            print('\n{}\n{}'.format('=' * 40, 'Was waiting for input, fix and retry'))
            break
        if 'Table widths have changed' not in outs:
            shutil.copy('{}.pdf'.format(base), currwd)
            os.chdir(currwd)
            print('Successfully processed')
            break
    else:
        os.chdir(currwd)
        raise RuntimeError('Tried {} times - table problems'.format(attempts))


def compile(template=None, document=None, **kwargs):
    '''Compile a document using the template'''
    with tempfile.TemporaryDirectory() as temp_dir:
        template_dir = os.path.dirname(template)
        doc_dir = os.path.dirname(document)
        template = shutil.copy(template, temp_dir)
        document = shutil.copy(document, temp_dir)
        if kwargs['replace']:
            replace(document, kwargs['replace'])

        my_env = modenv(['.', template_dir, os.path.join(template_dir, 'personal'),
                         doc_dir, os.path.join(doc_dir, 'personal')])
        _generate(temp_dir, my_env, template, document)


if __name__ == '__main__':
    parser = argparse.ArgumentParser('Compile a document')
    parser.add_argument('template', type=validFilePath, help='A latex template to apply')
    parser.add_argument('document', type=validFilePath, help='The document to apply the template to')
    parser.add_argument('-r', '--replace', type=validFilePath, help='A set of replacement patterns to apply to the document')
    args = parser.parse_args()
    compile(**vars(args))
