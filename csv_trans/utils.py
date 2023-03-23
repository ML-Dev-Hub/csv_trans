import os
import random
import time
import requests.exceptions
from multiprocessing import Pool, cpu_count

import chardet
import pandas as pd
from deep_translator import GoogleTranslator, exceptions

# Turn off warning
import warnings
warnings.filterwarnings("ignore")


def detect_encoding_scheme(file_path):
    """
    Detect encoding scheme of a CSV file

    --------------------
    Parameters:
        file_path: str
            The path to the file
    --------------------
    Returns:
        encoding_scheme: str
            The encoding scheme of the file
    """
    try:
        with open(file_path, 'rb') as f:
            rawdata = f.read(200)
        encoding_scheme = chardet.detect(rawdata)['encoding']
        return encoding_scheme
    except Exception as e:
        print(f"Error detecting encoding scheme: {e}")
        return None


def validate_dataframe(df):
    """
    Check if the data is a valid dataframe and not empty.

    --------------------
    Parameters:
        df: pandas.DataFrame
            The dataframe to be validated
    --------------------
    Returns:
        bool
            True if the dataframe is valid and not empty, False otherwise
    """
    if isinstance(df, pd.DataFrame) and not df.empty:
        return True
    return False


def translate_text(texts, target_language, source_language='en', chunk_size=4000, timeout=10):
    """
    Translate the text into the target language using Google Translator API

    --------------------
    Parameters:
        texts: list
            List of texts to be translated
        source_language: str
            The language of the input text
        target_language: str
            The target language to translate the text to
        chunk_size: int
            The size of chunk to split the input text
        timeout: int
            Timeout length for the request

    --------------------
    Returns:
        translations: list
            The list of translated texts
    """
    translations = []

    # Loop through all texts input
    for text in texts:
        # If the text is not in string format, add to translations list
        if not isinstance(text, str):
            translations.append(text)
            continue
        else:
            translated = ''
            try:
                random_seed = random.randint(1, 10)
                # sleep for nanoseconds
                time.sleep(random_seed / 100000)

                if len(text) < chunk_size:
                    translated = GoogleTranslator(
                        source=source_language, target=target_language, timeout=timeout).translate(text)
                else:
                    # split the data into 4000 characters while ensuring that the last word is space
                    split_data = split_text_data(text, chunk_size)
                    for i in split_data:
                        translated += GoogleTranslator(
                            source=source_language, target=target_language, timeout=timeout).translate(str(i))
            except exceptions.TranslationNotFound as e:
                print(f"Translation failed: {e}")
                translations.append(text)
            except requests.exceptions.Timeout as e:
                print(f"Translation timed out: {e}")
                translations.append(text)
            translations.append(translated)
    return translations


def split_text_data(text, chunk_size):
    """
    Split the input data/text into a fixed chunk size

    ----------------
        Parameters:
            text: str
                The input data to be split
            chunk_size: int
                The chunk size to split the data
    ----------------
        Returns:
            chunks: list
                The list of chunks
    """
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


def translate_dataframe(df, source_language, target_language):
    """
    Translate a given pandas DataFrame to a desired language

    ----------------
        Parameters:
            df: pandas.DataFrame
                The dataframe to be translated
            source_language: str
                The language of the input text
            target_language: str
                The target language to translate the text to
    ----------------
        Returns:
            result_df: pandas.DataFrame
                The translated dataframe
    """
    # Determine the number of threads to use based on the number of available CPU cores
    num_threads = min(cpu_count(), len(df.columns))
    # Create a Pool of worker threads and use the map function to apply the translate_text function to each column
    with Pool(num_threads) as pool:
        # Create a tuple of (column, source_language, target_language) for each column in dataframe
        column_args = [(df[column], target_language, source_language) for column in df.columns]
        # Using the pool, execute the translate_text function on each tuple of column arguments
        processed_columns = pool.starmap(translate_text, column_args)

    # Concatenate the resulting columns back together into a new DataFrame
    result_df = pd.concat([pd.Series(processed_columns[i], name=df.columns[i])
                           for i in range(len(processed_columns))], axis=1)

    return result_df


def read_csv_file(file_path, encoding_scheme, separator=','):
    """
    Read a CSV file using the given encoding scheme and delimiter

    ----------------
        Parameters:
            file_path: str
                The path to the input file
            encoding_scheme: str
                The encoding to use when reading the file
            separator: str
                The delimiter to use when reading the CSV file
    ----------------
        Returns:
            data: pandas.DataFrame
                The DataFrame containing the data from the CSV file
    """

    try:
        data = pd.read_csv(file_path, encoding=encoding_scheme, sep=separator, engine='pyarrow')
        return data
    except Exception as e:
        print(f"Error reading file {file_path}: {e}")
        return None


def save_csv_file(df, file_path, encoding_scheme):
    """
    Save a pandas DataFrame to a CSV file

    ----------------
    Parameters:
        df: pandas.DataFrame
            The DataFrame to be saved as CSV
        file_path: str
            The full path including the filename of the output file
        encoding_scheme: str
            The encoding scheme to use when saving the CSV file
    """

    path = os.path.dirname(file_path)
    file_name = os.path.basename(file_path)
    try:
        df.to_csv(os.path.join(path, "translated_" + file_name), encoding=encoding_scheme, index=False)
    except UnicodeEncodeError:
        df.to_csv(os.path.join(path, "translated_" + file_name), encoding='utf-8', index=False)
    except Exception as e:
        print(f"Error saving file {file_name}: {e}")
