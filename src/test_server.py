#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import logging
from PyQt4 import QtGui
from instantsoupdata import Server

# Initialize logger & set logging level
log = logging.getLogger("instantsoup")
log.setLevel(logging.DEBUG)
log.addHandler(logging.StreamHandler())

if __name__ == '__main__':
    app = QtGui.QApplication(sys.argv)
    server = Server()
    sys.exit(app.exec_())
