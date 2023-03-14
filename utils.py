import os
import random
import time
from multiprocessing import Pool, cpu_count

import chardet
import pandas as pd
from deep_translator import GoogleTranslator, exceptions


# turn off warning
import warnings
warnings.filterwarnings("ignore")


# function for splitting the text into chunks of given size
def split_text(text, chunk_size):
    chunks = []
    start = 0
    end = chunk_size

    while start < len(text):
        if end >= len(text):
            chunks.append(text[start:])
            break

        while text[end] != ' ' and end > start + chunk_size - 10:
            end -= 1

        if end <= start:
            end = start + chunk_size

        chunks.append(text[start:end])
        start = end + 1
        end = start + chunk_size
    return chunks


# function for translating the data using google translator api
def api_translate(data, source_language, target_language, chunk_size=4000):
    """
    Input: data, target_language
    Output: translated data
    Description: This function will translate the data into the target language using google translator
    """

    # if the data is not string then returning the data
    if not isinstance(data, str):
        return data

    translated = ''
    try:
        random_seed = random.randint(1, 10)
        # sleep for nanoseconds
        time.sleep(random_seed/10000)

        if len(data) < chunk_size:
            translated = GoogleTranslator(source=source_language, target=target_language).translate(data)
        else:
            # split the data into 4000 characters while ensuring that the last word is space
            split_data = split_text(data, chunk_size)
            for i in split_data:
                translated += GoogleTranslator(source=source_language, target=target_language).translate(str(i))
    except exceptions.TranslationNotFound as e:
        print(f"Translation failed: {e}")
        return data
    return translated


# function for reading the csv file using the encoding scheme
def read_csv_file(file_name, encoding_scheme, sep=','):
    """
    Input: file_name, encoding_scheme
    Output: data
    Description: This function will read the csv file using the encoding scheme
    """
    data = pd.read_csv(file_name, encoding=encoding_scheme, sep=sep, engine='pyarrow')
    return data


# function for finding the encoding scheme of the file
def find_encoding_scheme(file_name):
    """
    Input: file_name
    Output: encoding_scheme
    Description: This function will find the encoding scheme of the file
    """
    with open(file_name, 'rb') as f:
        rawdata = f.read(200)
    encoding_scheme = chardet.detect(rawdata)['encoding']
    return encoding_scheme


# function for saving the data into csv file
def save_csv_file(data, file_name, encoding_scheme):
    """
    Input: data, file_name, encoding_scheme
    Output: None
    Description: This function will save the data into csv file
    """
    data.to_csv("translated_" + file_name, encoding=encoding_scheme, index=False)


# function for processing the column
def process_column(args):
    # Unpack the arguments
    column, source_language, target_language = args
    # Perform some processing on the column here, e.g. apply a function or transformation
    processed_column = column.apply(lambda x: api_translate(x, source_language, target_language))
    return processed_column


# function for processing the dataframe
def process_dataframe(df, source_language, target_language):
    # Determine the number of threads to use based on the number of available CPU cores
    num_threads = min(cpu_count(), len(df.columns))
    # Create a Pool of worker threads and use the map function to apply the process_column function to each column
    with Pool(num_threads) as pool:
        processed_columns = pool.map(process_column, [(df[column], source_language, target_language)
                                                      for column in df.columns])

    # Concatenate the resulting columns back together into a new DataFrame
    result_df = pd.concat(processed_columns, axis=1)
    return result_df


# function for changing the ip address of the system
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


if __name__ == "__main__":
    # test the code
    print("Hello World")
