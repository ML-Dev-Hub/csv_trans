from src.csv_trans.translate import translate
import click


@click.command()
@click.option('--file_path', type=str, required=True, help='file path')
@click.option('--file_separator', type=str, required=True, help='file separator')
@click.option('--source_language', type=str, required=True, help='source language')
@click.option('--target_language', type=str, required=True, help='target language')


def main(file_path, file_separator, source_language, target_language):
    translate(file_path, source_language, target_language, file_separator)


if __name__ == '__main__':
    main()