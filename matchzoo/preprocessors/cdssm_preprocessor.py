"""CDSSM Preprocessor."""

import itertools
import logging
import typing

import numpy as np
from tqdm import tqdm

from matchzoo import DataPack, pack
from matchzoo import engine
from matchzoo import preprocessors

logger = logging.getLogger(__name__)


class CDSSMPreprocessor(engine.BasePreprocessor):
    """CDSSM preprocessor helper.

    Example:
        >>> train_inputs = [
        ...     ("id0", "id1", "beijing", "Beijing is capital of China", 1),
        ...     ("id0", "id2", "beijing", "China is in east Asia", 0),
        ...     ("id0", "id3", "beijing", "Summer in Beijing is hot.", 1)
        ... ]
        >>> cdssm_preprocessor = CDSSMPreprocessor()
        >>> rv_train = cdssm_preprocessor.fit_transform(
        ...     train_inputs,
        ...     stage='train')
        >>> type(rv_train)
        <class 'matchzoo.data_pack.DataPack'>
        >>> test_inputs = [("id0",
        ...                 "id4",
        ...                 "beijing",
        ...                 "I visted beijing yesterday.")]
        >>> rv_test = cdssm_preprocessor.fit_transform(
        ...     test_inputs,
        ...     stage='predict')
        >>> type(rv_test)
        <class 'matchzoo.data_pack.DataPack'>
    """

    def __init__(self,
                 text_length: int = 10,
                 pad_value: int = 0,
                 pad_mode: str = 'pre',
                 truncate_mode: str = 'pre'):
        """Initialization.

        :param text_length: fixed length of the text.
        :param pad_value: filling text with :attr:`pad_value` if
         text length is smaller than assumed.
        :param pad_mode: String, `pre` or `post`:
            pad either before or after each sequence.
        :param truncate_mode: String, `pre` or `post`:
            remove values from sequences larger than assumed,
            either at the beginning or at the end of the sequences.
        """
        self.data_pack = None
        self._text_length = text_length
        self._pad_value = pad_value
        self._pad_mode = pad_mode
        self._truncate_mode = truncate_mode

    def _prepare_process_units(self) -> list:
        """Prepare needed process units."""
        return [
            preprocessors.TokenizeUnit(),
            preprocessors.LowercaseUnit(),
            preprocessors.PuncRemovalUnit(),
            preprocessors.StopRemovalUnit(),
        ]

    def fit(self, inputs: typing.List[tuple]):
        """
        Fit pre-processing context for transformation.

        Can be simplified by compute vocabulary term and index.

        :param inputs: Inputs to be preprocessed.
        :return: class:`CDSSMPreprocessor` instance.
        """
        vocab = []
        units = self._prepare_process_units()
        units.append(preprocessors.NgramLetterUnit())

        logger.info("Start building vocabulary & fitting parameters.")

        # Convert user input into a data_pack object.
        self.data_pack = pack(inputs, stage='train')

        for idx, row in tqdm(self.data_pack.left.iterrows()):
            # For each piece of text, apply process unit sequentially.
            text = row.text_left
            for unit in units:
                text = unit.transform(text)
            vocab.extend(text)

        for idx, row in tqdm(self.data_pack.right.iterrows()):
            text = row.text_right
            for unit in units:
                text = unit.transform(text)
            vocab.extend(text)

        # Initialize a vocabulary process unit to build letter-ngram vocab.
        vocab_unit = preprocessors.VocabularyUnit()
        vocab_unit.fit(vocab)

        # Store the fitted parameters in context.
        self.data_pack.context['term_index'] = vocab_unit.state['term_index']
        self._dim_ngram = len(vocab_unit.state['term_index']) + 1
        self.data_pack.context['input_shapes'] = [
            (self._text_length, self._dim_ngram),
            (self._text_length, self._dim_ngram)
        ]
        return self

    @engine.validate_context
    def transform(
        self,
        inputs: typing.List[tuple],
        stage: str
    ) -> DataPack:
        """
        Apply transformation on data, create `letter-trigram` representation.

        :param inputs: Inputs to be preprocessed.
        :param stage: Pre-processing stage, `train`, `evaluate`, or `predict`.

        :return: Transformed data as :class:`DataPack` object.
        """
        if stage in ['evaluate', 'predict']:
            self.data_pack = pack(inputs, stage=stage)

        # prepare pipeline unit.
        units = self._prepare_process_units()
        ngram_unit = preprocessors.NgramLetterUnit()
        hash_unit = preprocessors.WordHashingUnit(
            self.data_pack.context['term_index'])
        fix_unit = preprocessors.FixedLengthUnit(
            self._text_length * self._dim_ngram, self._pad_value,
            self._pad_mode, self._truncate_mode)

        logger.info(f"Start processing input data for {stage} stage.")

        for idx, row in tqdm(self.data_pack.left.iterrows()):
            text = row.text_left
            for unit in units:
                text = unit.transform(text)
            text = [ngram_unit.transform([term]) for term in text]
            text = [hash_unit.transform(term) for term in text]
            # flatten the text vectors
            text = list(itertools.chain(*text))
            length = len(text)
            text = fix_unit.transform(text)
            length = min(length, self._text_length) * self._dim_ngram
            text = np.reshape(text, (self._text_length, -1))
            self.data_pack.left.at[idx, 'text_left'] = text.tolist()
            self.data_pack.left.at[idx, 'length_left'] = length

        for idx, row in tqdm(self.data_pack.right.iterrows()):
            text = row.text_right
            for unit in units:
                text = unit.transform(text)
            text = [ngram_unit.transform([term]) for term in text]
            text = [hash_unit.transform(term) for term in text]
            text = list(itertools.chain(*text))
            length = len(text)
            text = fix_unit.transform(text)
            length = min(length, self._text_length) * self._dim_ngram
            text = np.reshape(text, (self._text_length, -1))
            self.data_pack.right.at[idx, 'text_right'] = text.tolist()
            self.data_pack.right.at[idx, 'length_right'] = length

        return self.data_pack