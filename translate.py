import pandas as pd
import numpy as np
from utils import read_csv_file, find_encoding_scheme, api_translate


def translate(file, target_language, sep=','):
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
    for col in data.columns:
        data[col] = data[col].apply(lambda x: api_translate(x, target_language))
    return data


if __name__ == "__main__":
    #file path
    file_path = "urdu_headlines.csv"
    file_sperator = ","
    target_language = "en"
    
    translate_data = translate(file_path, target_language, sep=file_sperator)
    
    