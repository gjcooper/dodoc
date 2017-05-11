#!/bin/sh

TEMPLATE="$1"
DOCUMENT="$2"

IFS=. read base ext <<EOF
$DOCUMENT
EOF

folder=$(dirname "$DOCUMENT")

TEXINPUTS=.:$folder:$folder/personal:$TEXINPUTS

pandoc -f markdown -t latex --template=$TEMPLATE $DOCUMENT -o $base.tex

xelatex $base.tex

#rm $base.tex

scriptdir=$(dirname "$0")

rm $base.aux
rm $base.log
rm $base.out
rm texput.log

mv $base.pdf $folder/.
cd -
