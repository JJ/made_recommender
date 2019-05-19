import difflib
import json
import re

from common.base_script import BaseScript


class MatcherUtils(object):
    @staticmethod
    def normalize_name(name):
        name = re.sub('&',' and ', name)
        name = re.sub('(.)([A-Z][a-z]+)', r'\1 \2', name)
        name = re.sub('([a-z0-9])([A-Z])', r'\1 \2', name).lower()
        name = re.sub('[^a-z0-9 ]+', '', name)
        name = re.sub('([^\s])([0-9]+)', r'\1 \2', name)
        name = re.sub(' +', ' ', name)
        return name

    @staticmethod
    def similarity(source, target):
        seq = difflib.SequenceMatcher(None, source, target)
        return seq.ratio() * 100


class FilmInIMDB(object):
    def __init__(self, id, type, title, original_title, is_adult, start_year, end_year, minutes, genres):
        self.id = id
        self.type = type
        self.title = title
        self.original_title = original_title
        self.is_adult = is_adult
        self.start_year = start_year
        self.end_year = end_year
        self.minutes = minutes
        self.genres = self._split_genres(genres)
        self.normalized_title = MatcherUtils.normalize_name(self.title)

    @staticmethod
    def _split_genres(genres):
        if genres is None:
            return []
        return genres.replace('\n', '').split(',')


class FilmMapper(BaseScript):
    EXCLUDED_ENTRY_TYPES = ['tvEpisode', 'video', 'tvSeries', 'tvSpecial', 'tvShort', 'videoGame', 'tvMiniSeries',
                            'titleType']
    INCLUDE_FILMS_FROM_IMDB_WITHOUT_YEAR = False

    def __init__(self, tvtropes_films_file, imdb_titles_file, imdb_ratings_file, target_dataset):
        parameters = dict(tvtropes_films_file_name=tvtropes_films_file, imdb_titles_file=imdb_titles_file,
                          imdb_ratings_file=imdb_ratings_file, target_dataset=target_dataset,
                          excluded_entry_types=self.EXCLUDED_ENTRY_TYPES,
                          include_films_from_imdb_without_year=self.INCLUDE_FILMS_FROM_IMDB_WITHOUT_YEAR)

        BaseScript.__init__(self, parameters)

        self.tvtropes_films_file = tvtropes_films_file
        self.imdb_titles_file = imdb_titles_file
        self.imdb_ratings_file = imdb_ratings_file
        self.target_dataset = target_dataset

        self.film_list = []
        self.films_in_imdb = []
        self.films_in_imdb_hash = {}

    def run(self):
        self._load_information_from_imdb_dataset()
        self._load_information_from_tvtropes_dataset()
        self._map_films()
        self._finish_and_summary()
        pass

    def _load_information_from_imdb_dataset(self):
        self.films_in_imdb = []
        self.films_in_imdb_by_id = {}
        self.films_in_imdb_by_year = {}
        self.films_in_imdb_by_name = {}
        types = set()

        self._info(f'Loading basic information from IMDb dataset: {self.imdb_titles_file}')
        with open(self.imdb_titles_file, 'r') as films_imdb_titles:
            imdb_lines_counter = 0
            for line in films_imdb_titles:
                try:
                    components = line.split('\t')
                    types.add(components[1])
                    if self._is_included_due_type(components) and self._is_included_due_start_year(components):
                        film_in_imdb = FilmInIMDB(*components)

                        self.films_in_imdb.append(film_in_imdb)

                        year = film_in_imdb.start_year
                        name = film_in_imdb.normalized_title

                        self.films_in_imdb_by_id[film_in_imdb.id] = film_in_imdb

                        if not year in self.films_in_imdb_by_year:
                            self.films_in_imdb_by_year[year] = {}
                        if not name in self.films_in_imdb_by_year[year]:
                            self.films_in_imdb_by_year[year][name] = []
                        self.films_in_imdb_by_year[year][name].append(film_in_imdb)

                        if not name in self.films_in_imdb_by_name:
                            self.films_in_imdb_by_name[name] = []
                        self.films_in_imdb_by_name[name].append(film_in_imdb)


                        if len(self.films_in_imdb) % 50000 == 0:
                            self._info(f'{len(self.films_in_imdb)} films read')

                except Exception as exception:
                    self._track_error(f'Exception in line {line}. {exception}')
                finally:
                    imdb_lines_counter+=1

            self._add_to_summary('imdb_lines_counter', imdb_lines_counter)
            self._add_to_summary('imdb_films_considered', len(self.films_in_imdb))

        self._info(f'Adding ratings and votes from IMDb dataset: {self.imdb_ratings_file}')
        with open(self.imdb_ratings_file, 'r') as films_imdb_ratings:
            for line in films_imdb_ratings:
                try:
                    components = line.split('\t')
                    id = components[0]
                    rating = components[1]
                    votes = components[2]

                    if id in self.films_in_imdb_by_id:
                        self.films_in_imdb_by_id[id].rating = float(rating)
                        self.films_in_imdb_by_id[id].votes = float(votes)

                except Exception as exception:
                    self._track_error(f'Exception in line {line}. {exception}')

    def _is_included_due_type(self, components):
        return components[1] not in self.EXCLUDED_ENTRY_TYPES

    def _is_included_due_start_year(self, components):
        return self.INCLUDE_FILMS_FROM_IMDB_WITHOUT_YEAR or len(components[5])==4

    def _load_information_from_tvtropes_dataset(self):
        with open(self.tvtropes_films_file, 'r') as films_tvtropes:
            self.tropes_by_film = json.load(films_tvtropes)

    def _map_films(self):
        self.tvtropes_imdb_map = {}

        for film_name_tvtropes in self.tropes_by_film:
            self.tvtropes_imdb_map[film_name_tvtropes] = []

            if self._contains_year(film_name_tvtropes):
                year = film_name_tvtropes[-4:]
                name = MatcherUtils.normalize_name(film_name_tvtropes[:-4])
                if year in self.films_in_imdb_by_year and name in self.films_in_imdb_by_year[year]:
                    self.tvtropes_imdb_map[film_name_tvtropes].extend(self.films_in_imdb_by_year[year][name])
            else:
                name = MatcherUtils.normalize_name(film_name_tvtropes)
                if name in self.films_in_imdb_by_name:
                    self.tvtropes_imdb_map[film_name_tvtropes].extend(self.films_in_imdb_by_name[name])

        self._add_to_summary('Films matched times: 0', len(self._number_of_matches_equal(0)))
        self._add_to_summary('Films matched times: 1', len(self._number_of_matches_equal(1)))
        self._add_to_summary('Films matched times: 2', len(self._number_of_matches_equal(2)))
        self._add_to_summary('Films matched times: 3', len(self._number_of_matches_equal(3)))
        self._add_to_summary('Films matched times: 4+', len(self._number_of_matches_equal_or_higher(4)))


    @staticmethod
    def _contains_year(film_name):
        return re.fullmatch('^.+[1,2][0-9]{3}$', film_name)

    def _number_of_matches_equal(self, occurrences):
        return [name for name in self.tvtropes_imdb_map if len(self.tvtropes_imdb_map[name])==occurrences]

    def _number_of_matches_equal_or_higher(self, occurrences):
        return [name for name in self.tvtropes_imdb_map if len(self.tvtropes_imdb_map[name])>=occurrences]
