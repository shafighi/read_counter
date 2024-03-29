#!python3

import argparse
import pysam
import pandas as pd
import sys, getopt, re
from math import sqrt, log
from collections import defaultdict
import json
import os
from os import path
import ipdb
import pandas
import sys

pd.set_option('display.max_columns', None)
pd.set_option('display.expand_frame_repr', False)

# ------------------------------------------------------------------------

def vcfToDPgen( varFile,header ):
    for vr in varFile.fetch():
        dp = vr.samples[header]["DP"]
        yield ( vr.contig, vr.pos, dp )

def vcfToDPtab( varFileName,header ):
    varFile = pysam.VariantFile(varFileName)
    df = pd.DataFrame(
        vcfToDPgen( varFile,header ),
        columns = ( "contig", "pos", "dp" )
    )
    varFile.close()
    return df

# ------------------------------------------------------------------------


# Should generate a ranked list of top positions, based on total depth and on not-too-close coordinates
def rankDPtab( df, topNum = 100, blockSepDist = 2500 ):
    df["dpRank"] = df["dp"].rank(ascending=False)
    df.sort_values( by=["contig","pos"], ascending=[True,True], inplace=True )
    df["prevPosDist"] = df["pos"] - df.groupby(["contig"])["pos"].shift(1)
    df["diffBlock"] = ( df["prevPosDist"].isnull() | ( df["prevPosDist"] >= blockSepDist ) ).cumsum()
    ddf = df.loc[df.groupby(["diffBlock"])["dpRank"].idxmin()]
    ddf.sort_values( by=["dpRank"], ascending=[True], inplace=True )
    return ddf


# ------------------------------------------------------------------------


def vcfToSelVcf(inVarFileName, df):
    df.set_index(['contig', 'pos'], inplace=True)
    inVarFile = pysam.VariantFile(inVarFileName)
    for vr in inVarFile.fetch():
        if (vr.contig, vr.pos) in df.index:
            yield vr
    inVarFile.close()


# ------------------------------------------------------------------------

def alnToACgen( alnFileInfo, vr, contigLd = lambda chr: chr, minReadNum = 0, filterBarcodes = False ):
    #if (contigLd(vr.contig)).isdigit() or contigLd(vr.contig)=='X' or contigLd(vr.contig)=='Y':
    #	contig = 'chr' + contigLd(vr.contig)
    #elif contigLd(vr.contig)=='MT':
    #    contig = 'chrM'
    #else:
    #    contig = contigLd(vr.contig)
    contig = contigLd(vr.contig)
    counter = 0
    for pileupCol in alnFileInfo["af"].pileup(contig=contig, start=vr.pos - 1, stop=vr.pos, truncate=True, stepper="all"):
        cnt = 0
        if minReadNum >= 0:
            for pileupRead in pileupCol.pileups:
                if not pileupRead.is_del and not pileupRead.is_refskip and pileupCol.pos == vr.pos-1 :
                    cnt = cnt + 1
                #else:
                    #if(not pileupRead.is_del and not pileupRead.is_refskip):
                          #print(vr.pos)
                          #print(pileupCol.pos)
        if cnt < minReadNum or cnt==0:
            next
        for pileupRead in pileupCol.pileups:
            if not pileupRead.is_del and not pileupRead.is_refskip and pileupCol.pos == vr.pos-1:
                aln = pileupRead.alignment
                yield dict(
                        refPos=pileupCol.pos,
                        base=aln.query_sequence[pileupRead.query_position],
                        phred=aln.query_qualities[pileupRead.query_position],
                        strand="-" if aln.is_reverse else "+",
                        read=("2" if aln.is_read2 else "1") if aln.is_paired else "0"
                )

# ------------------------------------------------------------------------

class FullAcWriter:
    def posStart(self,vr):
        print( vr )

    def ac(self,ac,source):
        print( ac )

    def posEnd(self):
        print()


class SummaryAcWriter:
    def __init__(self, fileName):
        self._out = open(fileName, "w")
        self._firstElement = True

    def __del__(self):
        self._out.close()

    def posStart(self,vr):
        self._vr = vr
        self._acs = list()

    def ac(self,ac,source):
        ac["source"] = source;
        self._acs.append( ac )

    def posEnd(self):
        df = pd.DataFrame( self._acs )
        #print(df)
        umiDf = df.groupby(["source", "refPos", "base"]).size().reset_index(name='cnt')
        umiDf[ "refContig" ] = self._vr.contig
        umiDf[ "refAllele" ] = self._vr.ref
        #print(umiDf)
        #print("size:")
        #umiDf.groupby(["refContig", "refPos", "refAllele", "base", "source"]).size()
        #sumDf = umiDf.groupby(["refContig", "refPos", "refAllele", "base", "source"]).size().reset_index(name='cnt')
        #print(self._out)
        #print(sumDf)
        umiDf.to_csv( self._out, sep="\t", header=self._firstElement, index=False )
        self._firstElement = False
        #stop

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

# ------------------------------------------------------------------------

class AlleleCounterTool:
    def __init__(self,vcfFileName,outAcFileName,cellRangerGEXs,header,topNum=3000,blockSepDist=2500):
        self._topNum = topNum
        self._minReadNum = 0
        self._blockSepDist = blockSepDist
        self._filterBarcodes = True
        self._vcfFileName = vcfFileName
        self._outAcFileName = outAcFileName
        self._cellRangerGEXs = cellRangerGEXs
        self._header = header
        #print(vcfFileName)
    # info is a dict contain bam file name, bai ifile name, barcodes name
    def openAlnFiles(self,info):
        save = pysam.set_verbosity(0)
        info["af"] = pysam.AlignmentFile(info["bam"], "rb", index_filename=info["bai"].encode(), require_index=True)
        pysam.set_verbosity(save)
        if self._filterBarcodes:
            db = pandas.read_table(info["barcodes"])
            info["spots"] = db
        return info

    def run(self):
        #print(self._header)
        df = vcfToDPtab(self._vcfFileName,self._header)
        df = rankDPtab(df, topNum=self._topNum, blockSepDist=self._blockSepDist)
        # This for is for the cases which we have more than one set of files. usually we only have one
        openedAlnFileInfos = {id: self.openAlnFiles(info) for id, info in self._cellRangerGEXs.items()}
        with SummaryAcWriter(self._outAcFileName) as acWriter:
            # Each vr is a line in vcf file
            for vr in vcfToSelVcf(self._vcfFileName, df):
                isEmpty = False
                acWriter.posStart(vr)
                for id, afi in openedAlnFileInfos.items(): # for different set of files (set of wes and st for example)
                    for ac in alnToACgen(afi, vr, contigLd=lambda chr: chr, minReadNum=self._minReadNum,
                                         filterBarcodes=self._filterBarcodes):
                        isEmpty =  True
                        acWriter.ac(ac, source="file")
                if isEmpty:
                    acWriter.posEnd()

        for id, info in openedAlnFileInfos.items():
            info["af"].close()

#  ------------------------------------------------------------------------

crg = dict( { id: { "bam": sys.argv[1],"bai": sys.argv[2],"barcodes": sys.argv[3] } } )
print("inside")


print(sys.argv)

acTool = AlleleCounterTool(
        vcfFileName = sys.argv[4],
        outAcFileName = sys.argv[7]+sys.argv[5]+'.ac',
        cellRangerGEXs = crg,
        header = sys.argv[6],
        topNum = 3000,
        blockSepDist = 1
)
#print(crg)
if not path.exists(sys.argv[7]):
    os.makedirs(sys.argv[7])
acTool.run()
