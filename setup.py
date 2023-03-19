from setuptools import setup, find_packages

VERSION = '0.0.3'
DESCRIPTION = "A package for translating csv files across multiple languages"

LONG_DESCIPTION = """
## Universal Translator for csv files

This package is used to translate csv files across multiple languages. It uses google translator api to translate the csv-data from almost any source languague to any target language. It can handle almost all value types, even for large files, saving your time and effort. Say goodbye to manual translations and achieve professional and high-quality translations for your CSV files effortlessly with our CSV Translator.


## Installation
pip install csv-trans

## How to use it?
You can use it in two ways:
1. Using the command line interface (CLI) 
2. Using the import utility in your python code
    You can import the package and use the translate function to translate your csv file. You can use dogstrings to get more information about the function.
    For example:
    ```from csv_trans import translate```
    ```translate(file, source_language, target_language, sep=',')```


For Further information, checkout our Github page: 	https://github.com/ML-Dev-Hub/universal-translator-for-csv-files
    
     
## Contributors 


<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- prettier-ignore-start -->
<!-- markdownlint-disable -->
<table>
  <tbody>
    <tr>
      <td align="center"><a href="https://github.com/saeedahmadicp"><img src="https://avatars.githubusercontent.com/saeedahmadicp?v=4?s=100" width="100px;" alt="Saeed Ahmad"/><br /><sub><b>Saeed Ahmad</b></sub></a></td>
      <td align="center"><a href="https://github.com/ali-izhar"><img src="https://avatars3.githubusercontent.com/ali-izhar?v=4?s=100" width="100px;" alt="Izhar Ali"/><br /><sub><b>Izhar Ali</b></sub></a></td>
 </tr>
  </tbody>
</table>

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->

<!-- ALL-CONTRIBUTORS-LIST:END -->


"""




## Setting up
setup (
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
        "urllib3",
        ],
    entry_points={
        "console_scripts": [
            "csv_trans = csv_trans.__main__:cli"
        ]
    },
    keywords=['python', 'csv', 'translate', 'translator', 'google', 'google translator', 'google translate', 'translate csv'],
    classifiers=[
        "Programming Language :: Python :: 3",
        "Intended Audience :: Developers",
        "Operating System :: OS Independent",
        "License :: OSI Approved :: MIT License",
    ],
)