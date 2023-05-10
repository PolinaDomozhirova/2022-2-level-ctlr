"""
Pipeline for CONLL-U formatting
"""
from pathlib import Path
from typing import List
import string
import re

from pymorphy2 import MorphAnalyzer
from pymystem3 import Mystem

from core_utils.article.article import SentenceProtocol, split_by_sentence, get_article_id_from_filepath
from core_utils.article.io import from_raw, to_cleaned, to_conllu
from core_utils.article.ud import OpencorporaTagProtocol, TagConverter
from core_utils.constants import ASSETS_PATH


# pylint: disable=too-few-public-methods
class InconsistentDatasetError(Exception):
    """
    Exception raised when the dataset is inconsistent
    """
    pass


class EmptyDirectoryError(Exception):
    """
    Exception raised when the directory is empty
    """
    pass


class CorpusManager:
    """
    Works with articles and stores them
    """

    def __init__(self, path_to_raw_txt_data: Path):
        """
        Initializes CorpusManager
        """
        self.path_to_raw_txt_data = path_to_raw_txt_data
        self._validate_dataset()
        self._storage = {}
        self._scan_dataset()

    def _validate_dataset(self) -> None:
        """
        Validates folder with assets
        """
        if not self.path_to_raw_txt_data.exists():
            raise FileNotFoundError(f"No such file or directory: {self.path_to_raw_txt_data}")

        if not self.path_to_raw_txt_data.is_dir():
            raise NotADirectoryError(f"Not a directory: {self.path_to_raw_txt_data}")

        meta_files = list(self.path_to_raw_txt_data.glob('*_meta.json'))
        raw_files = list(self.path_to_raw_txt_data.glob('*_raw.txt'))

        if len(meta_files) != len(raw_files):
            raise InconsistentDatasetError('Number of meta and raw files is not equal')

        raw_ind = sorted([int(file.stem.split("_")[0]) for file in raw_files])
        meta_ind = sorted([int(file.stem.split("_")[0]) for file in meta_files])
        for id1, id2 in zip(raw_ind, raw_ind[1:]):
            if id2 - id1 > 1:
                raise InconsistentDatasetError('Article IDs are not sequential')

        for id1, id2 in zip(meta_ind, meta_ind[1:]):
            if id2 - id1 > 1:
                raise InconsistentDatasetError('Article IDs in meta data are not sequential')

        for raw_file in raw_files:
            if raw_file.stat().st_size == 0:
                raise InconsistentDatasetError

        for meta_file in meta_files:
            if meta_file.stat().st_size == 0:
                raise InconsistentDatasetError


    def _scan_dataset(self) -> None:
        """
        Register each dataset entry
        """
        for raw_file in self.path_to_raw_txt_data.glob("*_raw.txt"):
            file_id = get_article_id_from_filepath(raw_file)
            self._storage[file_id] = from_raw(raw_file)

    def get_articles(self) -> dict:
        """
        Returns storage params
        """
        return self._storage

class MorphologicalTokenDTO:
    """
    Stores morphological parameters for each token
    """

    def __init__(self, lemma: str = "", pos: str = "", tags: str = ""):
        """
        Initializes MorphologicalTokenDTO
        """
        self.lemma = lemma
        self.pos = pos
        self.tags = tags


class ConlluToken:
    """
    Representation of the CONLL-U Token
    """

    def __init__(self, text: str):
        """
        Initializes ConlluToken
        """
        self._text = text
        self.position = 0
        self._morphological_parameters = MorphologicalTokenDTO()

    def set_morphological_parameters(self, parameters: MorphologicalTokenDTO) -> None:
        """
        Stores the morphological parameters
        """
        self._morphological_parameters = parameters

    def set_position(self, position: int) -> None:
        self.position = position

    def get_morphological_parameters(self) -> MorphologicalTokenDTO:
        """
        Returns morphological parameters from ConlluToken
        """
        return self._morphological_parameters

    def get_conllu_text(self, include_morphological_tags: bool) -> str:
        """
        String representation of the token for conllu files
        """
        position = str(self.position)
        text = self._text
        lemma = self._morphological_parameters.lemma
        pos = self._morphological_parameters.pos
        xpos = '_'
        feats = self._morphological_parameters.tags \
            if include_morphological_tags and self._morphological_parameters.tags else '_'
        head = '0'
        deprel = 'root'
        deps = '_'
        misc = '_'
        return '\t'.join([position, text, lemma, pos,
                          xpos, feats, head, deprel, deps, misc])

    def get_cleaned(self) -> str:
        """
        Returns lowercase original form of a token
        """
        return self._text.lower().translate(str.maketrans('', '', string.punctuation))


class ConlluSentence(SentenceProtocol):
    """
    Representation of a sentence in the CONLL-U format
    """

    def __init__(self, position: int, text: str, tokens: list[ConlluToken]):
        """
        Initializes ConlluSentence
        """
        self._position = position
        self._text = text
        self._tokens = tokens

    def get_conllu_text(self, include_morphological_tags: bool) -> str:
        """
        Creates string representation of the sentence
        """
        conllu_tokens = []
        for token in self._tokens:
            conllu_tokens.append(token.get_conllu_text(include_morphological_tags))
        return f"# sent_id = {self._position}\n# text = {self._text}\n" + '\n'.join(conllu_tokens) + '\n'

    def get_cleaned_sentence(self) -> str:
        """
        Returns the lowercase representation of the sentence
        """
        return re.sub(r'\W+', '', self._text.lower())


    def get_tokens(self) -> list[ConlluToken]:
        """
        Returns sentences from ConlluSentence
        """
        return self._tokens



class MystemTagConverter(TagConverter):
    """
    Mystem Tag Converter
    """

    def convert_morphological_tags(self, tags: str) -> str:  # type: ignore
        """
        Converts the Mystem tags into the UD format
        """
        pos = self.convert_pos(tags)
        extracted_tags = re.findall(r'[а-я]+', tags.replace('(', '').replace(')', '').split('|')[0])

        pos_specific_categories = {
            "NOUN": [self.case, self.number, self.gender, self.animacy],
            "VERB": [self.tense, self.number, self.gender],
            "ADJ": [self.case, self.number, self.gender],
            "NUM": [self.case, self.number, self.gender],
            "PRON": [self.case, self.number, self.gender, self.animacy],
        }
        ud_tags = {category: self._tag_mapping[category][tag] for category in pos_specific_categories[pos]
                                                       for tag in extracted_tags
                                                       if tag in self._tag_mapping[category]}

        feats = '|'.join(f'{category}={value}' for category, value in sorted(ud_tags.items()))
        return feats


    def convert_pos(self, tags: str) -> str:  # type: ignore
        """
        Extracts and converts the POS from the Mystem tags into the UD format
        """
        pos_match = re.search(r'[A-Z]+', tags)
        return self._tag_mapping["POS"][pos_match[0]] if \
            pos_match and pos_match[0] in self._tag_mapping[
            "POS"] else ''


class OpenCorporaTagConverter(TagConverter):
    """
    OpenCorpora Tag Converter
    """

    def convert_pos(self, tags: OpencorporaTagProtocol) -> str:  # type: ignore
        """
        Extracts and converts POS from the OpenCorpora tags into the UD format
        """
        return self._tag_mapping[self.pos][tags.POS or 'UNKN']

    def convert_morphological_tags(self, tags: OpencorporaTagProtocol) -> str:  # type: ignore
        """
        Converts the OpenCorpora tags into the UD format
        """
        parsed_tags = {attr: getattr(tags, attr, None) for
                       attr in ['case', 'number', 'gender', 'animacy']}

        tags_list = []
        for category, value in parsed_tags.items():
            if value and value in self._tag_mapping.get(category, {}):
                mapped_value = self._tag_mapping[category][value]
                tags_list.append(f'{category}={mapped_value}')

        return '|'.join(tags_list)

class MorphologicalAnalysisPipeline:
    """
    Preprocesses and morphologically annotates sentences into the CONLL-U format
    """

    def __init__(self, corpus_manager: CorpusManager):
        """
        Initializes MorphologicalAnalysisPipeline
        """
        self._corpus = corpus_manager
        self._mystem_analyzer = Mystem()
        mapping_path = Path(__file__).parent / 'data' / 'mystem_tags_mapping.json'
        self._converter = MystemTagConverter(mapping_path)

    def _process(self, text: str) -> List[ConlluSentence]:
        """
        Returns the text representation as the list of ConlluSentence
        """
        sentences = []
        word_regex = re.compile(r'\w+|[.]')
        counter = 0

        for sentence_idx, sentence in enumerate(split_by_sentence(text)):
            conllu_tokens = []
            sentence_counter = 0
            mystem_analysis = self._mystem_analyzer.analyze(sentence)

            for token in mystem_analysis:
                if not word_regex.match(token['text']):
                    continue
                counter += 1
                sentence_counter += 1

                if token['text'].endswith('. '):
                    token['text'] = token['text'].replace('. ', '.')

                if token['text'].isalpha():
                    if 'analysis' in token and token['analysis']:
                        lemma, gram_info = token['analysis'][0]['lex'], token['analysis'][0]['gr']
                        pos = self._converter.convert_pos(gram_info)
                        tags = self._converter.convert_morphological_tags(gram_info)
                    else:
                        lemma, pos, tags = token['text'], 'X', ''
                elif token['text'].isdigit():
                    lemma, pos, tags = token['text'], 'NUM', ''
                else:
                    lemma, pos, tags = token['text'], 'PUNCT', ''

                conllu_token = ConlluToken(token['text'])
                conllu_token.set_position(sentence_counter)
                conllu_token.set_morphological_parameters(MorphologicalTokenDTO(lemma, pos, tags))
                conllu_tokens.append(conllu_token)

            sentence_obj = ConlluSentence(sentence_idx, sentence, conllu_tokens)
            sentences.append(sentence_obj)
            counter = sentence_counter

        return sentences


    def run(self) -> None:
        """
        Performs basic preprocessing and writes processed text to files
        """
        for article in self._corpus.get_articles().values():
            article.set_conllu_sentences(self._process(article.text))
            to_cleaned(article)
            to_conllu(article, include_morphological_tags=False, include_pymorphy_tags=False)
            to_conllu(article, include_morphological_tags=True, include_pymorphy_tags=False)

class AdvancedMorphologicalAnalysisPipeline(MorphologicalAnalysisPipeline):
    """
    Preprocesses and morphologically annotates sentences into the CONLL-U format
    """

    def __init__(self, corpus_manager: CorpusManager):
        """
        Initializes MorphologicalAnalysisPipeline
        """
        super().__init__(corpus_manager)
        self._backup_analyzer = MorphAnalyzer()
        mapping_path = Path(__file__).parent / 'data' / 'opencorpora_tags_mapping.json'
        self._backup_tag_converter = OpenCorporaTagConverter(mapping_path)


    def _process(self, text: str) -> List[ConlluSentence]:
        """
        Returns the text representation as the list of ConlluSentence
        """

    def run(self) -> None:
        """
        Performs basic preprocessing and writes processed text to files
        """


def main() -> None:
    """
    Entrypoint for pipeline module
    """
    manager = CorpusManager(ASSETS_PATH)
    morph_pipe = MorphologicalAnalysisPipeline(manager)
    morph_pipe.run()


if __name__ == "__main__":
    main()
