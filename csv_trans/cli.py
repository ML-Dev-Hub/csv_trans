from argparse import ArgumentParser
from csv_trans.translate import translate

def parse_arguments_from_cli(parser : ArgumentParser):
    '''
    Parse the arguments from the command line

    ----------------
        Parameters:
            parser: ArgumentParser
                The parser to parse the arguments from the command line
    ----------------
        Returns:
            parser: ArgumentParser
                The parser with the arguments parsed from the command line
    '''

    parser.add_argument('-f', '--file_path', type=str, required=True, help='file path')
    parser.add_argument('-fs', '--file_separator', type=str, default=',', required=False, help='file separator')
    parser.add_argument('-sl', '--source_language', type=str, required=True, help='source language')
    parser.add_argument('-tl', '--target_language', type=str, required=True, help='target language')
    return parser

def main():
    parser = ArgumentParser()
    parser = parse_arguments_from_cli(parser)
    args = parser.parse_args()
    translate(args.file_path, args.source_language, args.target_language, args.file_separator)