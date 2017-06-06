#!/usr/bin/env python
import argparse
import subprocess
import os
import tempfile
import shutil
import pdb


def validFilePath(possibleFilePath):
    if os.path.isfile(possibleFilePath):
        return os.path.abspath(possibleFilePath)
    msg = 'File: {} cannot be found'.format(possibleFilePath)
    raise argparse.ArgumentTypeError(msg)


def replace(document, patternfile):
    pass


def modenv(folderlist):
    env = os.environ.copy()

    prevTEX = env['TEXINPUTS'] if 'TEXINPUTS' in env else [':']
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

    for _ in range(attempts):
        print('Attempt number {}'.format(_))
        proc = subprocess.Popen(['xelatex', '{}.tex'.format(base)], stdout=subprocess.PIPE,
                                universal_newlines=True, env=my_env)
        outs = ''
        try:
            outs, errs = proc.communicate(timeout=5)
            if proc.returncode is None:
                continue
        except subprocess.TimeoutExpired:
            proc.kill()
            print('\n{}\n{}'.format('='*40, 'Was waiting for input, fix and retry'))
            break
        if 'Table widths have changed' not in outs:
            shutil.copy('{}.pdf'.format(base), currwd)
            os.chdir(currwd)
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
