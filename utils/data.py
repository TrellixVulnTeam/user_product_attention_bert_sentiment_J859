""" Download the data from: http://www.thunlp.org/~chm/data/data.zip """

import pdb
import torch
from torch.utils.data import Dataset
from collections import namedtuple
from pytorch_pretrained_bert.tokenization import BertTokenizer
import pickle
import os
import numpy as np
import zipfile
import wget
import numpy as np


Word = namedtuple('Word', ['idx', 'id'])
Doc = namedtuple('Doc', ['user_id', 'product_id', 'label', 'text',
                         'sentence_idx', 'mask', 'sentence_matrix', 'max_sentence_count'])

CACHE_PATH = 'datadrive/cache/'
DATASET_URL = 'http://www.thunlp.org/~chm/data/data.zip'

@classmethod
def cat_collate(cls, l):
    """ Concats the batches instead of stacking them like in the default_collate. """
    
    ret = torch.stack(l)
    pdb.set_trace()
    return ret
    


class SentimentDataset(Dataset):
    """ 
    Represents the sentiment dataset containing IMDB, Yelp13 and Yelp14. 
    Has to initialized for each set. Example:

    train_set = SentimentDataset(train_file, userlist_filename, productlist_filename, wordlist_filename)
    dev_set = SentimentDataset(dev_file, userlist_filename, productlist_filename, wordlist_filename)
    test_set = SentimentDataset(test_file, userlist_filename, productlist_filename, wordlist_filename)
    """

    def __init__(self, document_file, userlist_filename, productlist_filename, wordlist_filename, force_no_cache=False, chunk_size=5000):
        self.documents = dict()
        self.fields = ["user_id", "product_id", "label", "text",
                        "sentence_idx", "mask", "sentence_matrix", "max_sentence_count"]
        for label in self.fields[:-1]:
            self.documents[label] = []

        self.chunk_size = chunk_size

        if not os.path.exists('./data/yelp14'):
            wget.download(DATASET_URL)
            zf = zipfile.ZipFile(open("data.zip", "rb"))
            zf.extractall('data')
            os.remove('data.zip')

        self.tokenizer = BertTokenizer.from_pretrained(
            'bert-base-uncased', max_len=512)

        if not os.path.exists(CACHE_PATH):
            os.makedirs(CACHE_PATH)

        document_cache_path = CACHE_PATH + document_file.split('/')[-1]
        is_cached = sum([os.path.isfile(document_cache_path + "-" + label)
                         for label in self.fields]) == len(self.fields)
        self.users, self.user_string2int = self.read_userlist(
            userlist_filename)
        self.products, self.product_string2int = self.read_productlist(
            productlist_filename)
        self.word_list, self.vocabulary = self.read_vocabulary(
            wordlist_filename)
        if not is_cached or force_no_cache:
            self.read_documents(document_file, document_cache_path)
            print("Preprocessed {0} documents and cached to disk.".format(
                len(self.documents["user_id"])))
        else:
            self.read_docs_from_cache(document_cache_path)
            print("Loaded {0} documents from disk.".format(len(self.documents["user_id"])))

    def preprocess(self, text, sentence_delimeter='.'):
        """
        Takes text as input and does the:
            - tokenization
            - token to id conversion
            - calculate sentence positions
            - calculate the mask

        Args:
            text (str): Raw text of document.
            sentence_delimeter (str)

        Returns:
            token_ids (list of int): list containing the id of each token.
            sentence_idx (list of (int, int) ): list containing the beginning and end of each sentence. 
            mask (list of int): list of ones and zeros.
            sentence_matrix: matrix with dimensions (max_num_sentences, max_sequence_length). 
                             Each entry represents the token embedding id.
        """
        text = text.replace(sentence_delimeter, '[SEP]')
        tokenized = self.tokenizer.tokenize(text)
        tokenized = (['[CLS]'] + tokenized)  # + 512 * ['[PAD]'])[:512]

        sentence_idx = []
        sentence_lengths = []
        begin = 1  # first token is not part of a sentence
        for end, token in enumerate(tokenized):
            if token == '[SEP]':
                sentence_lengths.append(end-begin)
                begin = end+1

        cumsum = 1
        for sent_l in sentence_lengths:
            sentence_idx.append((cumsum, cumsum+sent_l))
            cumsum += sent_l

        sentence_idx += ([(-1, -1)] * (512-len(sentence_idx)))

        tokenized = ([token for token in tokenized if token !=
                      '[SEP]'] + 512 * ['[PAD]'])[:512]
        token_ids = self.tokenizer.convert_tokens_to_ids(tokenized)
        mask = [1 if token != 0 else 0 for token in token_ids]

        return token_ids, sentence_idx, mask

    def create_sentence_matrix(self, token_ids, sentence_idx):
        """
        Args:
            token_ids (list of int): list containing the id of each token.
            sentence_idx (list of (int, int) ): list containing the beginning and end of each sentence. 

        Returns:
            sentence_matrix (tensor of dimensions (max_sentences_per_doc, max_sentence_length) ): matrix where each row corresponds to the token ids of a sentence.
                                                                                                  Sentences and document are padded.
        """

        document = []
        for begin, end in sentence_idx:
            sentence_tokens = list(token_ids)[begin:end]
            padded_sntence_tokens = (sentence_tokens + self.max_sentence_length * [0])[:self.max_sentence_length]
            document.append(torch.tensor(
                padded_sntence_tokens, dtype=torch.int64))

            if begin == -1 or end == -1:
                break

        dummy_sentence = torch.tensor(
            self.max_sentence_length * [0], dtype=torch.int64)
        padded_document = (document + self.max_sentences_per_doc *
                           [dummy_sentence])[:self.max_sentences_per_doc]

        sentence_matrix = torch.stack(padded_document)

        return sentence_matrix

    def read_userlist(self, filename):
        """ Read userlist from file containing one user id per line. """
        lines = list(map(lambda x: x.split(),
                         open(userlist_filename).readlines()))
        user_list = [item[0] for item in lines]

        unique_users = list(set(user_list))
        string2int_id = {string_id: int_id for int_id,
                         string_id in enumerate(unique_users)}

        return user_list, string2int_id

    def read_productlist(self, filename):
        """ Read product list from file containing one product id per line. """
        lines = list(map(lambda x: x.split(),
                         open(filename).readlines()))
        product_list = [item[0] for item in lines]

        unique_products = list(set(product_list))
        string2int_id = {string_id: int_id for int_id,
                         string_id in enumerate(unique_products)}

        return product_list, string2int_id

    def read_vocabulary(self, filename):
        """ Read vocabulary from file containing one word per line. """
        lines = list(map(lambda x: x.split(),
                         open(wordlist_filename).readlines()))

        word_list = [item[0] for item in lines]
        vocab = {word: idx for idx, word in enumerate(word_list)}

        return word_list, vocab

    def read_documents(self, filename, cache_path):
        """
        Read reviews from file with each line containing:
        - user_id 
        - product_id 
        - review text seperated with double tabs('\t\t').

        Args:
            filename (str): the filepath of the documents
            cahce_path (str): the filepath to the documents cache

        Returns:
            docuements (list of Doc)
        """

        # limit the amount of documents for testing purposes if necessary
        lines = list(map(lambda x: x.split('\t\t'),
                         open(filename).readlines()))
        # lines = list(map(lambda x: x.split('\t\t'), open(filename).readlines()))

        self.count_long_text = 0
        max_sentence_count = 0
        for i, line in enumerate(lines):
            user_id, product_id, label, text = line

            label = int(label)-1  # classes are from 0-4 but starts from 1-5

            text, sentence_idx, mask = self.preprocess(
                text, sentence_delimeter='<sssss>')

            self.documents["user_id"].append(torch.tensor(
                self.user_string2int[user_id], dtype=torch.int64))
            self.documents["product_id"].append(torch.tensor(
                self.product_string2int[product_id], dtype=torch.int64))
            self.documents["label"].append(torch.tensor(label, dtype=torch.int64))
            self.documents["text"].append(torch.tensor(text, dtype=torch.int64))
            self.documents["sentence_idx"].append(torch.tensor(
                sentence_idx, dtype=torch.int64))
            self.documents["mask"].append(torch.tensor(mask, dtype=torch.int64))

            if len(sentence_idx) > max_sentence_count:
                max_sentence_count = len(sentence_idx)

            if i % 5000 == 0:
                print("Processed {0} of {1} documents. ({2:.1f}%)".format(
                    i, len(lines), i*100/len(lines)))
        
        flat_sentence_idx = []
        for doc_sent_idx in self.documents["sentence_idx"]:
            for idx in doc_sent_idx:
                flat_sentence_idx.append(idx)

        all_sentence_length = [end - begin for begin, end in flat_sentence_idx]
        self.max_sentence_length = int(max(all_sentence_length))

        tmp = []
        for i, s in enumerate(self.documents["sentence_idx"]):
            tmp.append([])
            for idx in s:
                if idx[0] != -1:
                    tmp[i].append(idx)
        
        all_sentence_count = [len(s) for s in tmp]
        self.max_sentences_per_doc = int(max(all_sentence_count))

        for i in range(len(self.documents["user_id"])):
            self.documents["sentence_matrix"].append(self.create_sentence_matrix(
                self.documents["text"][i],
                self.documents["sentence_idx"][i]
            ))


        self.documents["max_sentence_count"] = torch.tensor(max_sentence_count, dtype=torch.int64)
        
        for label in self.fields[:-1]:
            with open(cache_path + "-" + label, 'wb') as f:
                pickle.dump(len(self.documents['user_id']), f)
                n_docs = len(self.documents['user_id'])
                n_chunks = (n_docs//self.chunk_size)+1 
                for i in range(n_chunks):
                    if not i == n_chunks-1:
                        pickle.dump(self.documents[label][i*self.chunk_size:(i+1)*self.chunk_size], f)
                    else:
                        pickle.dump(self.documents[label][i*self.chunk_size:], f)
        torch.save(self.documents["max_sentence_count"], cache_path + "-max_sentence_count")

    def read_docs_from_cache(self, load_path):
        """ Loads the cached preprocessed documents from disk. """
        for label in self.fields[:-1]:
            with open(load_path + "-" + label, 'rb') as f:
                n_docs = pickle.load(f)
                self.documents[label] = []
                for i in range((n_docs//self.chunk_size)+1):
                    self.documents[label] += pickle.load(f)
        self.documents["max_sentence_count"] = torch.load(load_path + "-max_sentence_count")


    def __getitem__(self, idx):
        doc = [self.documents[label][idx] for label in self.fields[:-1]
                     ] + [self.documents["max_sentence_count"]] 
        return doc

    def __len__(self):
        return len(self.documents["user_id"])


userlist_filename = './data/yelp14/usrlist.txt'
productlist_filename = './data/yelp14/prdlist.txt'
wordlist_filename = './data/yelp14/wordlist.txt'
train_file = './data/yelp14/train.txt'
dev_file = './data/yelp14/dev.txt'
test_file = './data/yelp14/test.txt'


if __name__ == '__main__':
    """ Just to test. """
    ds = SentimentDataset(train_file, userlist_filename,
                          productlist_filename, wordlist_filename, force_no_cache=True)
    print("Max number of sentences per document: {0}".format(len(ds.documents["sentence_matrix"][0])))
    print("Max number of words per sentence: {0}".format(len(ds.documents["sentence_matrix"][0][0])))
    # print(ds.documents["sentence_matrix"][0])
