import pandas as pd
import numpy as np
from utils import read_csv_file, find_encoding_scheme, api_translate, save_csv_file
import tqdm

def translate(file, source_language, target_language, sep=','):
    """
    Input: file, target_language
    Output: translated data
    
    Description: This function will translate the data into the target language using google translator
    """
    ## find the encoding scheme
    encoding_scheme = find_encoding_scheme(file)
    ## read the csv file
    data = read_csv_file(file, encoding_scheme, sep=sep)
    ## translate the data
    for col in tqdm.tqdm(data.columns):
        data[col] = data[col].apply(lambda x: api_translate(x, source_language, target_language))
        
    ## save the data to the csv file
    save_csv_file(data, file, encoding_scheme, sep=sep)
    



## create a function that takes arguments as file path, target language, file seperator using cmd and parameters
def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--file_path', type=str, required=True, help='file path')
    parser.add_argument('--file_sperator', type=str, required=True, help='file seperator')
    parser.add_argument('--source_language', type=str, required=True, help='source language')
    parser.add_argument('--target_language', type=str, required=True, help='target language')
    args = parser.parse_args()
    translate(args.file_path, args.source_language ,args.target_language, sep=args.file_sperator)


if __name__ == "__main__":
    main()
    
    