from setuptools import setup, find_packages

VERSION = '0.0.4'
DESCRIPTION = "A package for translating csv files across multiple languages"


## Setting up
setup (
    name="csv_trans",
    version=VERSION,
    author="Saeed Ahmad",
    author_email="saeedahmad.icp@gmail.com",
    description=DESCRIPTION,
    long_description=open('README.md').read(),
    long_description_content_type="text/markdown",
    url="https://github.com/ML-Dev-Hub/universal-translator-for-csv-files",
    packages=find_packages(),
    python_requires=">=3.6",
    install_requires=[
        "click==8.0.3",
        "beautifulsoup4==4.11.2",
        "certifi==2022.12.7",
        "chardet==5.1.0",
        "charset-normalizer==3.1.0",
        "colorama==0.4.6",
        "deep-translator==1.10.1",
        "idna==3.4",
        "numpy==1.24.2",
        "pandas==1.5.3",
        "pyarrow==11.0.0",
        "python-dateutil==2.8.2",
        "pytz==2022.7.1",
        "requests==2.28.2",
        "six==1.16.0",
        "soupsieve==2.4",
        "tqdm==4.65.0",
        "urllib3==1.26.14",
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