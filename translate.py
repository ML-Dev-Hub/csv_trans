from deep_translator import GoogleTranslator
from utils import read_csv_file, find_encoding_scheme, api_translate, save_csv_file, process_dataframe
from tqdm import tqdm

# Get the list of supported languages
translator = GoogleTranslator()
supported_languages = translator.get_supported_languages(as_dict=True).keys()


def translate(file, source_language, target_language, sep=','):
    """
    Input: file, target_language
    Output: translated data
    Description: This function will translate the data into the target language using google translator api
    """

    encoding_scheme = find_encoding_scheme(file)
    data = read_csv_file(file, encoding_scheme, sep=sep)

    # Display a waiting message while the function is executing
    with tqdm(total=1, desc="Translating DataFrame") as pbar:
        data = process_dataframe(data, source_language, target_language)
        pbar.update()

    # save the data to the csv file
    save_csv_file(data, file, encoding_scheme)


# create a function that takes arguments as file path, target language, file seperator using cmd and parameters
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Translate the data into the target language',
        usage="python translate.py --file_path=../data/translated_data.csv --file_separator=',' --source_language=en "
              "--target_language=hi"
    )
    parser.add_argument('--file_path', type=str, required=True, help='file path')
    parser.add_argument('--file_separator', type=str, required=True, help='file separator')
    parser.add_argument('--source_language', type=str, required=True, help='source language')
    parser.add_argument('--target_language', type=str, required=True, help='target language')
    args = parser.parse_args()

    if args.source_language not in supported_languages:
        print("Source language is not supported")
        print("Supported languages are: ", ", ".join(i for i in supported_languages))
        return

    if args.target_language not in supported_languages:
        print("Target language is not supported")
        print("Supported languages are: ", ", ".join(i for i in supported_languages))
        return

    translate(args.file_path, args.source_language, args.target_language, args.file_separator)


if __name__ == "__main__":
    main()
