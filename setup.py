from setuptools import setup, find_packages

VERSION = '0.0.2'
DESCRIPTION = "A package for translating csv files across multiple languages"

LONG_DESCIPTION = """
# Universal Translator for csv files
This package is used to translate csv files across different languages. It uses the Google Translate API to translate 
the csv files from a source language to a target language. Supported languages are listed 
[here](https://cloud.google.com/translate/docs/languages). The package can handle csv files with multiple columns and 
rows and can translate the whole file in one go, saving your time and effort. 

## Installation
```bash
pip install csv-trans
```

## How to use it?
You can use the package in two ways:
1. Using the command line interface (CLI)
2. Using the import utility in your python code.

Both the CLI and the import utility take the same arguments. The only difference is that the CLI takes the arguments 
as command line arguments while the import utility takes the arguments as function arguments. 
The arguments are listed below.

1. `--file` or `-f`: The path to the source csv file.
2. `--source_language` or `-sl`: The source language of the csv file. The default value is `en`.
3. `--target_language` or `-tl`: The target language of the csv file. The default value is `ur`.
4. `--sep` or `-s`: The separator used in the csv file. The default value is `,`.

### Using the import utility
```bash
from csv_trans import translate
translate(file, source_language, target_language, sep=',')
```

For Further information, checkout our [GitHub Page](https://github.com/ML-Dev-Hub/universal-translator-for-csv-files).
     
## Contributors ✨
<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- prettier-ignore-start -->
<!-- markdownlint-disable -->
<table>
  <tbody>
    <tr>
      <td align="center"><a href="https://github.com/saeedahmadicp"><img src="https://avatars.githubusercontent.com/saeedahmadicp?v=4?s=100" width="100px;" alt="Saeed Ahmad"/><br /><sub><b>Saeed Ahmad</b></sub></a><br /><a href="https://github.com/ML-Dev-Hub/universal-translator-for-csv-files/commits?author=saeedahmadicp" title="Code">💻</a> <a href="https://github.com/ML-Dev-Hub/universal-translator-for-csv-files/commits?author=saeedahmadicp" title="Documentation">📖</a></td>
      <td align="center"><a href="https://github.com/ali-izhar"><img src="https://avatars3.githubusercontent.com/ali-izhar?v=4?s=100" width="100px;" alt="Izhar Ali"/><br /><sub><b>Izhar Ali</b></sub></a><br /><a href="https://github.com/ML-Dev-Hub/universal-translator-for-csv-files/commits?author=ali-izhar" title="Code">💻</a><a href="https://github.com/ML-Dev-Hub/universal-translator-for-csv-files/commits?author=ali-izhar" title="Documentation">📖</a></td></td>
 </tr>
  </tbody>
</table>

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->

<!-- ALL-CONTRIBUTORS-LIST:END -->
"""

setup(
    name="csv_trans",
    version=VERSION,
    author="Saeed Ahmad",
    author_email="saeedahmad.icp@gmail.com",
    description=DESCRIPTION,
    long_description=LONG_DESCIPTION,
    long_description_content_type="text/markdown",
    url="https://github.com/ML-Dev-Hub/universal-translator-for-csv-files",
    packages=find_packages(),
    python_requires=">=3.6",
    install_requires=[
        "click",
        "beautifulsoup4",
        "certifi",
        "chardet",
        "charset-normalizer",
        "colorama",
        "deep-translator==1.10.1",
        "googletrans",
        "idna",
        "numpy",
        "pandas",
        "pyarrow",
        "python-dateutil",
        "pytz",
        "requests",
        "six",
        "soupsieve",
        "tqdm",
        "urllib3"
        ],
    entry_points={
        "console_scripts": [
            "csv_trans = csv_trans.__main__:cli"
        ]
    },
    keywords=['python', 'csv', 'translate', 'translator', 'google',
              'google translator', 'google translate', 'translate csv'],
    classifiers=[
        "Programming Language :: Python :: 3",
        "Intended Audience :: Developers",
        "Operating System :: OS Independent",
        "License :: OSI Approved :: MIT License",
    ],
)
