"""British English spelling rules for SRT subtitles."""

# American -> British spelling replacements
_BRITISH_SPELLINGS = {
    "color": "colour",
    "colors": "colours",
    "favor": "favour",
    "favors": "favours",
    "favorite": "favourite",
    "favorites": "favourites",
    "honor": "honour",
    "honors": "honours",
    "humor": "humour",
    "labor": "labour",
    "labors": "labours",
    "neighbor": "neighbour",
    "neighbors": "neighbours",
    "neighborhood": "neighbourhood",
    "organize": "organise",
    "organizes": "organises",
    "organized": "organised",
    "organizing": "organising",
    "organization": "organisation",
    "organizations": "organisations",
    "recognize": "recognise",
    "recognizes": "recognises",
    "recognized": "recognised",
    "recognizing": "recognising",
    "realize": "realise",
    "realizes": "realises",
    "realized": "realised",
    "realizing": "realising",
    "analyze": "analyse",
    "analyzes": "analyses",
    "analyzed": "analysed",
    "analyzing": "analysing",
    "defense": "defence",
    "offense": "offence",
    "license": "licence",
    "practice": "practise",
    "center": "centre",
    "centers": "centres",
    "theater": "theatre",
    "theaters": "theatres",
    "meter": "metre",
    "meters": "metres",
    "liter": "litre",
    "liters": "litres",
    "fiber": "fibre",
    "fibers": "fibres",
    "catalog": "catalogue",
    "catalogs": "catalogues",
    "dialog": "dialogue",
    "dialogs": "dialogues",
    "program": "programme",
    "programs": "programmes",
    "traveled": "travelled",
    "traveling": "travelling",
    "traveler": "traveller",
    "travelers": "travellers",
    "canceled": "cancelled",
    "canceling": "cancelling",
    "modeled": "modelled",
    "modeling": "modelling",
    "labeled": "labelled",
    "labeling": "labelling",
    "jewelry": "jewellery",
    "gray": "grey",
    "aging": "ageing",
    "judgment": "judgement",
    "acknowledgment": "acknowledgement",
    "fulfill": "fulfil",
    "fulfills": "fulfils",
    "enrollment": "enrolment",
    "installment": "instalment",
}


def apply_british_spelling(text: str) -> str:
    """Replace American English spellings with British equivalents."""
    def _replace_line(line: str) -> str:
        words = line.split()
        result = []
        for word in words:
            prefix = ""
            suffix = ""
            clean = word
            while clean and not clean[0].isalpha():
                prefix += clean[0]
                clean = clean[1:]
            while clean and not clean[-1].isalpha():
                suffix = clean[-1] + suffix
                clean = clean[:-1]

            lower = clean.lower()
            if lower in _BRITISH_SPELLINGS:
                replacement = _BRITISH_SPELLINGS[lower]
                if clean.isupper():
                    replacement = replacement.upper()
                elif clean[0].isupper() if clean else False:
                    replacement = replacement[0].upper() + replacement[1:]
                result.append(prefix + replacement + suffix)
            else:
                result.append(word)
        return " ".join(result)

    return "\n".join(_replace_line(line) for line in text.split("\n"))
