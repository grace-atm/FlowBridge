class sourceFile():
    def __init__(self, fileID, fileName=None, fileContent=None):
        self.fileID = fileID
        self.fileName = fileName
        self.fileContent = fileContent

    def __str__(self):
        return fileContent

class pyProject():
    def __init__(self, projectID, projectName, files=[]):
        self.projectID = projectID
        self.projectName = projectName
        self.files=list[sourceFile]

    def 