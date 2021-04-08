#!/bin/bash

st_bam_file="/home/shafighi/alireza/stpipeline/st_1.2/annotated.bam"
st_bai_file="/home/shafighi/alireza/stpipeline/st_1.2/annotated.bam.bai"
barcode="/home/shafighi/calling_from_BAM/barcodes/1000L2_barcodes_header.txt"
vcf_file="/home/shafighi/calling_from_BAM/output/vardict/w12_blood.vcf"
output_name="vardict2_1.2"
tumor_column_vcf="w12"


python st_read_counter.py $st_bam_file  $st_bai_file  $barcode  $vcf_file  $output_name  $tumor_column_vcf
