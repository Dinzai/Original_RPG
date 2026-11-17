class TranspileError(ValueError):
    def __init__(self, filename, node, message, source=''):
        self.filename = str(filename)
        self.line = getattr(node, 'lineno', 1)
        self.column = getattr(node, 'col_offset', 0) + 1
        self.message = message
        lines = source.splitlines()
        excerpt = lines[self.line - 1] if 0 < self.line <= len(lines) else ''
        super().__init__(f'{filename}:{self.line}:{self.column}: {message}' +
                         (f'\n    {excerpt}\n    {" " * (self.column - 1)}^' if excerpt else ''))

    def as_dict(self):
        return dict(file=self.filename, line=self.line, column=self.column, message=self.message)
