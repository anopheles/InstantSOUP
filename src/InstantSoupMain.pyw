#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
InstantSOUP
===========

The "Instant Satisfaction by Obscure Unstable Protocol" (InstantSOUP) is an application-level protocol for local message exchange.
The protocol was developed during a telematics project at Karlsruhe Institute of Technology (KIT) during the course of the winter semester 2011/2012.
InstantSOUP is responsible for connecting the user to a lobby in his or her local area network.
In this environment the user is able to interact with other participants and chat rooms.
"""

import sys


from instantsoupdata import *
from PyQt4 import QtCore, QtGui, uic

try:
    _fromUtf8 = QtCore.QString.fromUtf8
except AttributeError:
    _fromUtf8 = lambda s: s

class MainWindow(QtGui.QMainWindow):
    
    def __init__(self):
        super(MainWindow, self).__init__()
        
        self.initUI()
        
    def initUI(self):
        self.resize(800, 600)
        self.setWindowTitle('InstantSoup - Group 1')
        
        tabWidget = QtGui.QTabWidget()
        tabWidget.setTabsClosable(True)
        tabWidget.setMovable(True)
        tabWidget.setObjectName(_fromUtf8("tabWidget"))
        
        tabLobby = uic.loadUi("gui/lobbyWidget.ui")
        tabLobby.setObjectName(_fromUtf8("tabLobby"))
        
        tabWidget.addTab(tabLobby, _fromUtf8("Lobby"))
        
        tabChannel = uic.loadUi("gui/ChannelWidget.ui")
        tabChannel.setObjectName(_fromUtf8("tabChannel"))
        
        tabWidget.addTab(tabChannel, _fromUtf8("Channel"))
        
        gridLayout = QtGui.QGridLayout()
        gridLayout.setSizeConstraint(QtGui.QLayout.SetDefaultConstraint)
        gridLayout.setContentsMargins(9, -1, -1, -1)
        gridLayout.setHorizontalSpacing(6)
        gridLayout.setObjectName(_fromUtf8("gridLayout"))
        
        gridLayout.addWidget(tabWidget, 0, 0, 1, 1)
        
        centralWidget = QtGui.QWidget()
        centralWidget.setLayout(gridLayout)
        self.setCentralWidget(centralWidget)
        

if __name__ == '__main__':
    app = QtGui.QApplication(sys.argv)
    mainWindow = MainWindow()  
    mainWindow.show()
    sys.exit(app.exec_())

"""
    data = InstantSoupData.peerPDU.build(Container(ClientID = "Bob",
                                                   Option = [Container(OptionID = "SERVER_INVITE_OPTION",
                                                                       OptionData = Container(ChannelID = "TM2011",
                                                                                              ClientID = ["Alice", "Billy"])),
                                                             Container(OptionID = "CLIENT_NICK_OPTION",
                                                                       OptionData = "Susan")]))

    print repr(data)
    packet = InstantSoupData.peerPDU.parse(data)
    print packet
"""
