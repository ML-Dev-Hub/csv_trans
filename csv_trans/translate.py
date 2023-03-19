from googletrans import LANGUAGES
from tqdm import tqdm
import argparse
from .utils import detect_encoding_scheme, validate_dataframe, read_csv_file, save_csv_file, translate_dataframe

__all__ = ['translate', 'main']


def translate(file: str, source_lang: str, target_lang: str, sep: str = ',') -> None:
    """
    Translates the data in the file to the target language and saves the result
    """
    encoding_scheme = detect_encoding_scheme(file)
    # read the data from the csv file
    data = read_csv_file(file, encoding_scheme, sep)
    if not validate_dataframe(data):
        print("Unable to read data from file")
        return

    # rename the column of the dataframe from the source language to the target language
    data = data.rename(columns={data.columns[1]: target_lang})

    # Display a waiting message while the function is executing
    with tqdm(total=1, desc="Translating DataFrame") as pbar:
        # translate the data
        data = translate_dataframe(data, source_lang, target_lang)
        pbar.update()

    # save the data to the csv file
    save_csv_file(data, file, encoding_scheme)


# make file_separator optional
def main(file_path: str, source_language: str, target_language: str, file_separator: str = ',') -> None:
    """
    Translate the data in file_path to the target_language and save the result to the same file.
    """
    parser = argparse.ArgumentParser(
        description='Translate the data into the target language',
    )
    parser.add_argument('-f', '--file-path', type=str, required=True, help='file path')
    parser.add_argument('-fs', '--file-separator', type=str, required=True, help='file separator')
    parser.add_argument('-sl', '--source-language', type=str, required=True, help='source language')
    parser.add_argument('-tl', '--target-language', type=str, required=True, help='target language')
    args = parser.parse_args([f"--file-path={file_path}", f"--file-separator={file_separator}",
                              f"--source-language={source_language}", f"--target-language={target_language}"])

    wrong_args = False
    if args.source_language not in LANGUAGES.keys() and args.source_language not in LANGUAGES.values():
        print("Source language is not supported")
        wrong_args = True

    if args.target_language not in LANGUAGES.keys() and args.target_language not in LANGUAGES.values():
        print("Target language is not supported")
        wrong_args = True

    if wrong_args:
        print("Supported languages are: ", ", ".join([f"{k} ({v})" for k, v in LANGUAGES.items()]))
        return

    translate(args.file_path, args.source_language, args.target_language, args.file_separator)
