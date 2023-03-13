import pandas as pd
import numpy as np
import time
import random
import os

import chardet
from deep_translator import GoogleTranslator, MyMemoryTranslator

## turn off warning
import warnings
warnings.filterwarnings("ignore")

## function for changing the IP address of the system
def change_ip_address():
    """
    Input: None
    Output: None
    
    Description: This function will change the IP address of the system
    """
    os.system("ipconfig /release")
    os.system("ipconfig /renew")
    os.system("ipconfig /flushdns")
    os.system("ipconfig /registerdns")
    os.system("ipconfig /renew6")
    os.system("ipconfig /flushdns")


## spliting the data to chunks of 4000 characters
def split_text(text):
    chunks = []
    start = 0
    end = 4000

    while start < len(text):
        if end >= len(text):
            chunks.append(text[start:])
            break

        while text[end] != ' ' and end > start + 4000 - 10:
            end -= 1

        if end <= start:
            end = start + 4000

        chunks.append(text[start:end])
        start = end + 1
        end = start + 4000

    return chunks

## api for translation the values in the column
def api_translate(data, source_language, target_language):
    ## write dog string to the file
    """
    Input: data, target_language
    Output: translated data
    
    Description: This function will translate the data into the target language using google translator
    """
    translated = ''
    try:
        random_seed = random.randint(1, 1000)
        ## sleep for nanoseconds
        time.sleep(random_seed/1000)
        
        if len(data) < 4000:
            translated = GoogleTranslator(source=source_language, target=target_language).translate(data)
        else:
            ## split the data into 4000 characters while ensuring that the last word is space
            split_data = split_text(data)
            
            for i in split_data:
                translated += GoogleTranslator(source=source_language, target=target_language).translate(i)      
    except:
        ## print the catch error
        print("Error in translating the data")
        print("type error: " + str(TypeError))
        
        
    return translated

### reading any csv file, using different encoding scheme
def read_csv_file(file_name, encoding_scheme, sep = ','):
    """
    Input: file_name, encoding_scheme
    Output: data
    
    Description: This function will read the csv file using the encoding scheme
    """
    data = pd.read_csv(file_name, encoding = encoding_scheme, sep = sep, engine='pyarrow')
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


## function for saving the data into csv file
def save_csv_file(data, file_name, encoding_scheme, sep = ','):
    """
    Input: data, file_name, encoding_scheme
    Output: None
    
    Description: This function will save the data into csv file
    """
    data.to_csv(file_name + "_translated.csv", encoding = encoding_scheme, sep = sep, index = False)
    
if __name__ == "__main__":
    #test 
    print("Hello World")
