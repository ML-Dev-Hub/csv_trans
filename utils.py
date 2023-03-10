import pandas as pd
import numpy as np
import time

import chardet
from deep_translator import GoogleTranslator

## turn off warning
import warnings
warnings.filterwarnings("ignore")



## api for translation the values in the column
def api_translate(data, target_language):
    ## write dog string to the file
    """
    Input: data, target_language
    Output: translated data
    
    Description: This function will translate the data into the target language using google translator
    """
    try:
        translated = GoogleTranslator(source='auto', target=target_language).translate(data)
    except:
        ## os sleep for 2 seconds
        
        ## check for the system and sleep for 2 seconds 
        time.sleep(2)
        translated = GoogleTranslator(source='auto', target=target_language).translate(data)
    return translated



### reading any csv file, using different encoding scheme
def read_csv_file(file_name, encoding_scheme):
    """
    Input: file_name, encoding_scheme
    Output: data
    
    Description: This function will read the csv file using the encoding scheme
    """
    data = pd.read_csv(file_name, encoding = encoding_scheme)
    return data


## finding the encoding scheme of the file
def find_encoding_scheme(file_name):
    """
    Input: file_name
    Output: encoding_scheme
    
    Description: This function will find the encoding scheme of the file
    """
    with open(file_name, 'rb') as f:
        rawdata = f.read()
    encoding_scheme = chardet.detect(rawdata)['encoding']
    return encoding_scheme


    
if __name__ == "__main__":
    #test 
    print("Hello World")