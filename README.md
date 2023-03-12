## Unviversal Translator for csv files

Our open-source translation tool provides accurate and efficient translations for CSV files across languages. Our advanced technology can handle all value types, even for large files, saving you time and effort. Say goodbye to manual translations and achieve professional and high-quality translations for your CSV files effortlessly.

## Setup
- open the terminal
- clone the repository
	```bash
	git clone https://github.com/ML-Dev-Hub/universal-translator-for-csv-files.git
	```
- change the directory

	```bash
	cd universal-translator-for-csv-files
	```
- execute the below commands
 	```bash
	pip3 install pipenv
	```
	```bash
	pipenv install
	```
	```bash
	pipenv shell
	```
	
- install the requirements 
	```bash
	pip install -r requirements.txt
	```

- translate your csv file by executing the code
	```bash
	python translate.py --file_path <file_path> --file_sperator <file_seperator> --source_language <source_language> --target_language <target_language>
	```
	below is the example for translating the csv file: 
	```bash
	python translate.py --file_path urdu_headlines.csv --file_sperator , --source_language ur --target_language en
	```
       
