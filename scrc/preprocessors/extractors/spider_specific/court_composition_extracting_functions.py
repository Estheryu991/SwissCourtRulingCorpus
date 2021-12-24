from pathlib import Path
import re
import json
from typing import Dict, Optional, Tuple
from scrc.data_classes.court_composition import CourtComposition
from scrc.data_classes.court_person import CourtPerson

from scrc.enums.court_role import CourtRole
from scrc.enums.gender import Gender
from scrc.enums.language import Language
from scrc.enums.political_party import PoliticalParty
from scrc.enums.section import Section

"""
This file is used to extract the judicial persons from decisions sorted by spiders.
The name of the functions should be equal to the spider! Otherwise, they won't be invocated!
Overview of spiders still todo: https://docs.google.com/spreadsheets/d/1FZmeUEW8in4iDxiIgixY4g0_Bbg342w-twqtiIu8eZo/edit#gid=0
"""


def XX_SPIDER(sections: Dict[Section, str], namespace: dict) -> Optional[str]:
    # This is an example spider. Just copy this method and adjust the method name and the code to add your new spider.

    # header = sections[Section.HEADER] to get a specific section
    pass


# check if court got assigned shortcut: SELECT count(*) from de WHERE lower_court is not null and lower_court <> 'null' and lower_court::json#>>'{court}'~'[A-Z0-9_]{2,}';
def CH_BGer(sections: Dict[Section, str], namespace: dict) -> Optional[str]:
    """
    Extract judicial persons from decisions of the Federal Supreme Court of Switzerland
    :param sections:    the dict containing the sections per section key
    :param namespace:   the namespace containing some metadata of the court decision
    :return:            the sections dict
    """

    header = sections[Section.HEADER]

    information_start_regex = r'Besetzung|Bundesrichter|Composition( de la Cour:)?|Composizione|Giudic[ie] federal|composta'
    role_regexes = {
        Gender.MALE: {
            CourtRole.JUDGE: [r'Bundesrichter(?!in)', r'MM?\.(( et|,) Mmes?)? les? Juges?( fédéra(l|ux))?',
                       r'[Gg]iudici federali'],
            CourtRole.CLERK: [r'Gerichtsschreiber(?!in)', r'Greffier[^\w\s]*', r'[Cc]ancelliere']
        },
        Gender.FEMALE: {
            CourtRole.JUDGE: [r'Bundesrichterin(nen)?', r'Mmes? l(a|es) Juges? (fédérales?)?',
                       r'MMe et MM?\. les? Juges?( fédéra(l|ux))?', r'[Gg]iudice federal'],
            CourtRole.CLERK: [r'Gerichtsschreiberin(nen)?', r'Greffière.*Mme', r'[Cc]ancelliera']
        }
    }

    skip_strings = get_skip_strings()

    start_pos = re.search(information_start_regex, header)
    if start_pos:
        header = header[start_pos.span()[0]:]
    end_pos = {
        Language.DE: re.search(r'.(?=(1.)?(Partei)|(Verfahrensbeteiligt))', header) or re.search('Urteil vom',
                                                                                          header) or re.search(
            r'Gerichtsschreiber(in)?\s\w*.', header) or re.search(r'[Ii]n Sachen', header) or re.search(r'\w{2,}\.',
                                                                                                        header),
        Language.FR: re.search(r'.(?=(Parties|Participant))', header) or re.search(r'Greffi[eè]re? M(\w)*\.\s\w*.', header),
        Language.IT: re.search(r'.(?=(Parti)|(Partecipant))', header) or re.search(r'[Cc]ancellier[ae]:?\s\w*.',
                                                                            header) or re.search(r'\w{2,}\.', header),
    }
    end_pos = end_pos[namespace['language']]
    if end_pos:
        header = header[:end_pos.span()[1] - 1]

    header = header.replace(';', ',')
    header = header.replace('Th', '')
    header = header.replace(' und ', ', ')
    header = header.replace(' et ', ', ')
    header = header.replace(' e ', ', ')
    header = header.replace('MMe', 'Mme')
    header = re.sub(r'(?<!M)(?<!Mme)(?<!MM)(?<!\s\w)\.', ', ', header)
    header = re.sub(r'MM?\., Mme', 'M. et Mme', header)
    header = re.sub(r'Mmes?, MM?\.', 'MMe et M', header)
    header = header.replace('federali, ', 'federali')
    besetzungs_strings = header.split(',')

    def prepare_french_name_and_find_gender(person: CourtPerson) -> CourtPerson:
        """Removes the prefix from a french name and sets gender"""
        if person.name.find('M. ') > -1:
            person.name = person.name.replace('M. ', '')
            person.gender = Gender.MALE
        elif person.name.find('Mme') > -1:
            person.name = person.name.replace('Mme ', '')
            person.gender = Gender.FEMALE
        return CourtPerson

    besetzung = CourtComposition()
    current_role = CourtRole.JUDGE
    last_person: CourtPerson = None
    last_gender = Gender.MALE

    for text in besetzungs_strings:
        text = text.strip()
        if len(text) == 0 or text in skip_strings[namespace['language']]:
            continue
        if re.search(r'(?<![Vv]ice-)[Pp]r[äée]sid',
                     text):  # Set president either to the current person or the last Person (case 1: Präsident Niklaus, case 2: Niklaus, Präsident)
            if last_person:
                besetzung.president = last_person
                continue
            else:
                text = text.split()[-1]
                president, _ = match_person_to_database(CourtPerson(text, last_gender, current_role), last_gender)
                besetzung.president = president
        has_role_in_string = False
        matched_gender_regex = False
        for gender in role_regexes:  # check for male and female all roles
            if matched_gender_regex:
                break
            role_regex = role_regexes[gender]
            for regex_key in role_regex:  # check each role
                regex = '|'.join(role_regex[regex_key])
                role_pos = re.search(regex, text)
                if role_pos: # Found a role regex
                    last_role = current_role
                    current_role = regex_key
                    name_match = re.search(r'[A-Z][A-Za-z\-éèäöü\s]*(?= Urteil)|[A-Z][A-Za-z\-éèäöü\s]*(?= )',
                                           text[role_pos.span()[1] + 1:])
                    name = name_match.group() if name_match else text[role_pos.span()[1] + 1:]
                    if len(name.strip()) == 0:
                        if (last_role == CourtRole.CLERK and len(besetzung.clerks) == 0) or (last_role == CourtRole.JUDGE and len(besetzung.judges) == 0):
                            break

                        last_person_name = besetzung.clerks.pop().name if (last_role == CourtRole.CLERK) else besetzung.clerks.pop().name # rematch in database with new role
                        last_person_new_match, _ = match_person_to_database(CourtPerson(name=last_person_name, court_role=current_role), gender)
                        if current_role == CourtRole.JUDGE:
                            besetzung.judges.append(last_person_new_match)
                        elif current_role == CourtRole.CLERK:
                            besetzung.clerks.append(last_person_new_match)
                    if namespace['language'] == Language.FR:
                        person = prepare_french_name_and_find_gender(name)
                        gender = person.gender or gender
                        person.court_role = current_role
                    else:
                        person = CourtPerson(name=name, court_role=current_role)
                    matched_person, _ = match_person_to_database(person, gender)
                    if current_role == CourtRole.JUDGE:
                        besetzung.judges.append(matched_person)
                    elif current_role == CourtRole.CLERK:
                        besetzung.clerks.append(matched_person)
                    last_person = matched_person
                    last_gender = matched_person.gender
                    has_role_in_string = True
                    matched_gender_regex = True
                    break
        if not has_role_in_string:  # Current string has no role regex match
            if namespace['language'] == Language.FR:
                person = prepare_french_name_and_find_gender(text)
                last_gender = person.gender or last_gender
            else:
                person = CourtPerson(text, last_gender, current_role)
            name_match = re.search(
                r'[A-Z][A-Za-z\-éèäöü\s]*(?= Urteil)|[A-Z][A-Za-z\-éèäöü\s]*(?= )|[A-Z][A-Za-z\-éèäöü\s]*', person.name)
            if not name_match:
                continue
            name = name_match.group()
            person.court_role = current_role
            matched_person, _ = match_person_to_database(person, last_gender)
            if current_role == CourtRole.JUDGE:
                besetzung.judges.append(matched_person)
            elif current_role == CourtRole.CLERK:
                besetzung.clerks.append(matched_person)
            last_person = person
    return besetzung


def ZG_Verwaltungsgericht(sections: Dict[Section, str], namespace: dict) -> Optional[str]:
    """
    Extract judicial persons from decisions of the Verwaltungsgericht of Zug
    :param header:      the string containing the header
    :param namespace:   the namespace containing some metadata of the court decision
    :return:            the sections dict
    """
    
    header = sections[Section.HEADER]

    role_regexes = {
        Gender.MALE: {
            CourtRole.JUDGE: [r'Richter(?!in)', r'Einzelrichter(?!in)'],
            CourtRole.CLERK: [r'Gerichtsschreiber(?!in)']
        },
        Gender.FEMALE: {
            CourtRole.JUDGE: [r'Richterin(nen)?',r'Einzelrichterin(nen)?'],
            CourtRole.CLERK: [r'Gerichtsschreiberin(nen)?']
        }
    }

    skip_strings = get_skip_strings()

    information_start_regex = r'Mitwirkende|Einzelrichter'
    start_pos = re.search(information_start_regex, header)
    if start_pos:
        header = header[start_pos.span()[0]:]

    information_end_regex = r'Urteil|U R T E I L|URTEIL'
    end_pos = re.search(information_end_regex, header)
    if end_pos:
        header = header[:end_pos.span()[1] - 1]

    besetzungs_strings = get_besetzungs_strings(header)

    besetzung = CourtComposition()
    current_role = CourtRole.JUDGE
    last_person: CourtPerson = None
    person: CourtPerson = None
    last_gender = Gender.MALE

    for text in besetzungs_strings:
        text = text.strip()
        if len(text) == 0 or text in skip_strings[namespace['language']]:
            continue
        if re.search(r'(?<![Vv]ice-)[Pp]r[äée]sid',
                     text):  # Set president either to the current person or the last Person (case 1: Präsident Niklaus, case 2: Niklaus, Präsident)
            if last_person:
                besetzung.president = last_person
                continue
            else:
                text = text.split()[-1]
                president, _ = match_person_to_database(CourtPerson(text), last_gender)
                besetzung.president = president
        has_role_in_string = False
        matched_gender_regex = False
        for gender in role_regexes:  # check for male and female all roles
            if matched_gender_regex:
                break
            role_regex = role_regexes[gender]
            for regex_key in role_regex:  # check each role
                regex = '|'.join(role_regex[regex_key])
                role_pos = re.search(regex, text)
                if role_pos: # Found a role regex
                    last_role = current_role
                    current_role = regex_key
                    name_match = re.search(r'[A-Z][A-Za-z\-éèäöü\s]*(?= Urteil)|[A-Z][A-Za-z\-éèäöü\s]*(?= )',
                                           text[role_pos.span()[1] + 1:])
                    name = name_match.group() if name_match else text[role_pos.span()[1] + 1:]
                    if len(name.strip()) == 0:
                        if (last_role == CourtRole.CLERK and len(besetzung.clerks) == 0) or (last_role == CourtRole.JUDGE and len(besetzung.judges) == 0):
                            break

                        last_person_name = besetzung.clerks.pop().name if (last_role == CourtRole.CLERK) else besetzung.clerks.pop().name # rematch in database with new role
                        last_person_new_match, _ = match_person_to_database(CourtPerson(name=last_person_name, court_role=current_role), gender)
                        if current_role == CourtRole.JUDGE:
                            besetzung.judges.append(last_person_new_match)
                        elif current_role == CourtRole.CLERK:
                            besetzung.clerks.append(last_person_new_match)
                    matched_person, _ = match_person_to_database(person, gender)
                    if current_role == CourtRole.JUDGE:
                        besetzung.judges.append(matched_person)
                    elif current_role == CourtRole.CLERK:
                        besetzung.clerks.append(matched_person)
                    last_person = matched_person
                    last_gender = matched_person.gender
                    has_role_in_string = True
                    matched_gender_regex = True
                    break
        if not has_role_in_string:  # Current string has no role regex match
            if current_role not in besetzung:
                besetzung[current_role] = []
            name_match = re.search(
                r'[A-Z][A-Za-z\-éèäöü\s]*(?= Urteil)|[A-Z][A-Za-z\-éèäöü\s]*(?= )|[A-Z][A-Za-z\-éèäöü\s]*', person.name)
            if not name_match:
                continue
            name = name_match.group()
            person.court_role = current_role
            matched_person, _ = match_person_to_database(person, last_gender)
            if current_role == CourtRole.JUDGE:
                besetzung.judges.append(matched_person)
            elif current_role == CourtRole.CLERK:
                besetzung.clerks.append(matched_person)
            last_person = person
    return besetzung


def ZH_Baurekurs(sections: Dict[Section, str], namespace: dict) -> Optional[str]:
    """
    Extract judicial persons from decisions of the Baurekursgericht of Zurich
    :param header:      the string containing the header
    :param namespace:   the namespace containing some metadata of the court decision
    :return:            the sections dict
    """
    header = sections[Section.HEADER]
    print(header)

    role_regexes = {
        Gender.MALE: {
            CourtRole.JUDGE: [r'Abteilungspräsident(?!in)', r'Baurichter(?!in)', r'Abteilungsvizepräsident(?!in)', r'Ersatzrichter(?!in)'],
            CourtRole.CLERK: [r'Gerichtsschreiber(?!in)']
        },
        Gender.FEMALE: {
            CourtRole.JUDGE: [r'Abteilungspräsidentin(nen)?',r'Baurichterin(nen)?', r'Abteilungsvizepräsidentin(nen)?', r'Ersatzrichterin(nen)?'],
            CourtRole.CLERK: [r'Gerichtsschreiberin(nen)?']
        }
    }

    skip_strings = get_skip_strings()

    information_start_regex = r'Mitwirkende'
    start_pos = re.search(information_start_regex, header)
    if start_pos:
        header = header[start_pos.span()[0]:]

    information_end_regex = r'in Sachen '
    end_pos = re.search(information_end_regex, header)
    if end_pos:
        header = header[:end_pos.span()[1] - 1]
    
    besetzungs_strings = get_besetzungs_strings(header)

    besetzung = CourtComposition()
    current_role = CourtRole.JUDGE
    last_person: CourtPerson = None
    last_gender = Gender.MALE

    pass

def ZH_Obergericht(sections: Dict[Section, str], namespace: dict) -> Optional[str]:
    """
    Extract judicial persons from decisions of the Obergericht of Zurich
    :param header:      the string containing the header
    :param namespace:   the namespace containing some metadata of the court decision
    :return:            the sections dict
    """

    header = sections[Section.HEADER]

    role_regexes = {
        Gender.MALE: {
            CourtRole.JUDGE: [r'Oberrichter(?!in)', r'Ersatzrichter(?!in)'],
            CourtRole.CLERK: [r'Gerichtsschreiber(?!in)']
        },
        Gender.FEMALE: {
            CourtRole.JUDGE: [r'Oberrichterin(nen)?',r'Ersatzrichterin(nen)?'],
            CourtRole.CLERK: [r'Gerichtsschreiberin(nen)?']
        }
    }

    skip_strings = get_skip_strings()

    information_start_regex = r'Mitwirkend:'
    start_pos = re.search(information_start_regex, header)
    if start_pos:
        header = header[start_pos.span()[0]:]
    
    information_end_regex = r'Beschluss vom|Urteil vom|Beschluss und Urteil vom'
    end_pos = re.search(information_end_regex, header)
    if end_pos:
        header = header[:end_pos.span()[1] - 1]
    
    besetzungs_strings = get_besetzungs_strings(header)

    besetzung = CourtComposition()
    current_role = CourtRole.JUDGE
    last_person: CourtPerson = None
    last_gender = Gender.MALE
        
    pass


def ZH_Sozialversicherungsgericht(sections: Dict[Section, str], namespace: dict) -> Optional[str]:
    """
    Extract judicial persons from decisions of the Sozialversicherungsgericht of Zurich
    :param header:      the string containing the header
    :param namespace:   the namespace containing some metadata of the court decision
    :return:            the sections dict
    """

    header = sections[Section.HEADER]

    role_regexes = {
        Gender.MALE: {
            CourtRole.JUDGE: [r'Sozialversicherungsrichter(?!in)', r'Ersatzrichter(?!in)'],
            CourtRole.CLERK: [r'Gerichtsschreiber(?!in)']
        },
        Gender.FEMALE: {
            CourtRole.JUDGE: [r'Sozialversicherungsrichterin(nen)?',r'Ersatzrichterin(nen)?'],
            CourtRole.CLERK: [r'Gerichtsschreiberin(nen)?']
        }
    }

    skip_strings = get_skip_strings()

    information_start_regex = r'Mitwirkende|Einzelrichter'
    start_pos = re.search(information_start_regex, header)
    if start_pos:
        header = header[start_pos.span()[0]:]

    information_end_regex = r'Urteil vom|in Sachen'
    end_pos = re.search(information_end_regex, header)
    if end_pos:
        header = header[:end_pos.span()[1] - 1]
    
    besetzungs_strings = get_besetzungs_strings(header)

    besetzung = CourtComposition()
    current_role = CourtRole.JUDGE
    last_person: CourtPerson = None
    last_gender = Gender.MALE
        
    pass

def ZH_Steuerrekurs(sections: Dict[Section, str], namespace: dict) -> Optional[str]:
    """
    Extract judicial persons from decisions of the Steuerrekursgericht of Zurich
    :param header:      the string containing the header
    :param namespace:   the namespace containing some metadata of the court decision
    :return:            the sections dict
    """

    header = sections[Section.HEADER]

    role_regexes = {
        Gender.MALE: {
            CourtRole.JUDGE: [r'Abteilungspräsident(?!in)', r'Steuerrichter(?!in)', r'Ersatzrichter(?!in)', r'Einzelrichter(?!in)'],
            CourtRole.CLERK: [r'Gerichtsschreiber(?!in)']
        },
        Gender.FEMALE: {
            CourtRole.JUDGE: [r'Abteilungspräsidentin(nen)?',r'Steuerrichterin(nen)?',r'Ersatzrichterin(nen)?',r'Einzelrichterin(nen)?'],
            CourtRole.CLERK: [r'Gerichtsschreiberin(nen)?']
        }
    }

    skip_strings = get_skip_strings()

    information_start_regex = r'Mitwirkend:'
    start_pos = re.search(information_start_regex, header)
    if start_pos:
        header = header[start_pos.span()[0]:]
    
    information_end_regex = r'In Sachen|in Sachen'
    end_pos = re.search(information_end_regex, header)
    if end_pos:
        header = header[:end_pos.span()[1] - 1]
    
    besetzungs_strings = get_besetzungs_strings(header)

    besetzung = CourtComposition()
    current_role = CourtRole.JUDGE
    last_person: CourtPerson = None
    last_gender = Gender.MALE
        
    pass

def ZH_Verwaltungsgericht(sections: Dict[Section, str], namespace: dict) -> Optional[str]:
    """
    Extract judicial persons from decisions of the Verwaltungsgericht of Zurich
    :param header:      the string containing the header
    :param namespace:   the namespace containing some metadata of the court decision
    :return:            the sections dict
    """

    header = sections[Section.HEADER]

    role_regexes = {
        Gender.MALE: {
            CourtRole.JUDGE: [r'Abteilungspräsident(?!in)', r'Verwaltungsrichter(?!in)'],
            CourtRole.CLERK: [r'Gerichtsschreiber(?!in)']
        },
        Gender.FEMALE: {
            CourtRole.JUDGE: [r'Abteilungspräsidentin(nen)?',r'Verwaltungsrichterin(nen)?'],
            CourtRole.CLERK: [r'Gerichtsschreiberin(nen)?']
        }
    }

    skip_strings = get_skip_strings()

    information_start_regex = r'Mitwirkend:'
    start_pos = re.search(information_start_regex, header)
    if start_pos:
        header = header[start_pos.span()[0]:]

    information_end_regex = r'In Sachen|in Sachen'
    end_pos = re.search(information_end_regex, header)
    if end_pos:
        header = header[:end_pos.span()[1] - 1]

    besetzungs_strings = get_besetzungs_strings(header)

    besetzung = CourtComposition()
    current_role = CourtRole.JUDGE
    last_person: CourtPerson = None
    last_gender = Gender.MALE
        
    pass



def get_besetzungs_strings(header: str) -> list:
    header = header.replace(';', ',')
    header = header.replace(' und ', ', ')
    header = header.replace(' sowie ', ', ')
    header = header.replace('lic. ', '')
    header = header.replace('iur. ', '')
    header = header.replace('Dr. ', '')
    header = header.replace('MLaw ', '')
    header = header.replace('PD ', '')
    header = header.replace(' als Einzelrichterin', '')
    header = header.replace(' als Einzelrichter', '')
    return header.split(',')


def get_skip_strings() -> dict:
    return {
        Language.DE: ['Einzelrichter', 'Konkurskammer', 'Beschwerdeführerin', 'Beschwerdeführer', 'Kläger', 'Berufungskläger'],
        Language.FR: ['Juge suppléant', 'en qualité de juge unique'],
        Language.IT: ['Giudice supplente', 'supplente']
    }


def match_person_to_database(person: CourtPerson, current_gender: Gender) -> Tuple[CourtPerson, bool]:
    """"Matches a name of a given role to a person from personal_information.json if found it adds the party and selects more accurate CourtRole"""
    personal_information_database = json.loads(Path("personal_information.json").read_text())

    results = []
    name = person.name.replace('.', '').strip()
    split_name = name.split()
    initial = False
    if len(split_name) > 1:
        initial = next((x for x in split_name if len(x) == 1), None)
        split_name = list(filter(lambda x: len(x) > 1, split_name))
    if person.court_role.value in personal_information_database:
        for subcategory in personal_information_database[person.court_role.value]:
            for cat_id in personal_information_database[person.court_role.value][subcategory]:
                for db_person in personal_information_database[person.court_role.value][subcategory][cat_id]:
                    if set(split_name).issubset(set(db_person['name'].split())):
                        if not initial or re.search(rf'\s{initial.upper()}\w*', db_person['name']):
                            person.name = db_person['name']
                            if db_person.get('gender'):
                                person.gender = Gender(db_person['gender'])
                            if db_person.get('party'):
                                person.party = PoliticalParty(db_person['party'])
                            results.append(person)
    else:
        for existing_role in personal_information_database:
            temp_person = CourtPerson(person.name, court_role=CourtRole(existing_role))
            db_person, match = match_person_to_database(temp_person, current_gender)
            if match:
                results.append(db_person)
    if len(results) == 1:
        if not results[0].gender:
            results[0].gender = current_gender
        return person, True
    return person, False

