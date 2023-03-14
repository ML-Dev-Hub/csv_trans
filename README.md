
## Universal Translator for csv files

This open-source translation tool provides accurate and efficient translations for CSV files across languages. It can handle almost all value types, even for large files, saving you time and effort. Say goodbye to manual translations and achieve professional and high-quality translations for your CSV files effortlessly.


## Setup
To install the Universal Translator, run the following commands:

- clone the repository
	```bash
	git clone https://github.com/ML-Dev-Hub/universal-translator-for-csv-files.git
	```
- change the directory
	```bash
	cd universal-translator-for-csv-files
	```
- setup your virtual environment
 	```bash
	pip3 install pipenv
	pipenv install
	pipenv shell
	```
	
- install the requirements 
	```bash
	pip install -r requirements.txt
	```

- translate your csv file by executing the code in this prompt:
	```bash
	python translate.py --file_path <file_path> --file_separator <file_seperator> --source_language <source_language> --target_language <target_language>
	```
	Example use-case for translating a csv file:
	```bash
	python translate.py --file_path english.csv --file_separator , --source_language ur --target_language en
	```
     
