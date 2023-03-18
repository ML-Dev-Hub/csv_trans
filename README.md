
## Universal Translator for csv files

This open-source translation tool provides accurate and efficient translations for CSV files across multiple languages. It can handle almost all value types, even for large files, saving your time and effort. Say goodbye to manual translations and achieve professional and high-quality translations for your CSV files effortlessly with our csv-translator.

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
	python translate.py --file_path english.csv --file_separator , --source_language english --target_language urdu
	```
     
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
