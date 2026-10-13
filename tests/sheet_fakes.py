"""In-memory stand-ins for gspread's Spreadsheet and Worksheet (only the
methods src/export/sheets.py uses)."""


class FakeWS:
    def __init__(self, values=None, title=""):
        self.values = values or []
        self.title = title

    def get_all_values(self):
        return self.values

    def resize(self, rows, cols):
        pass

    def update(self, values, start, value_input_option=None):
        self.values = [list(r) for r in values]

    def format(self, *a, **k):
        pass

    def freeze(self, *a, **k):
        pass


class FakeBook:
    def __init__(self, sheets):
        self.sheets = sheets
        for name, ws in sheets.items():
            ws.title = name

    def worksheet(self, name):
        import gspread
        if name not in self.sheets:
            raise gspread.WorksheetNotFound(name)
        return self.sheets[name]

    def worksheets(self):
        return list(self.sheets.values())

    def add_worksheet(self, title, rows, cols):
        self.sheets[title] = FakeWS(title=title)
        return self.sheets[title]

    def del_worksheet(self, ws):
        del self.sheets[ws.title]
