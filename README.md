# Universal Translator for csv files

Our open-source translation tool provides accurate and efficient translations for CSV files across languages. The advanced technology used in the tool can handle all value types, even for large files, saving you time and effort. Say goodbye to manual translations and achieve professional and high-quality translations for your CSV files effortlessly with our Universal Translator. The tool is easy to use and customizable to your specific translation needs.

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
	python translate.py --file_path=urdu_headlines.csv --file_separator=',' --source_language='ur' --target_language='en'
	```
     
