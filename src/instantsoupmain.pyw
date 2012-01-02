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

from PyQt4 import QtCore, QtGui, uic
from instantsoupdata import InstantSoupData


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

        tab_widget = QtGui.QTabWidget()
        tab_widget.setTabsClosable(True)
        tab_widget.setMovable(True)
        tab_widget.setObjectName(_fromUtf8("tab_widget"))

        tab_lobby = uic.loadUi("gui/lobbyWidget.ui")
        tab_lobby.setObjectName(_fromUtf8("tab_lobby"))

        tab_widget.addTab(tab_lobby, _fromUtf8("Lobby"))

        tab_channel = uic.loadUi("gui/ChannelWidget.ui")
        tab_channel.setObjectName(_fromUtf8("tab_channel"))

        tab_widget.addTab(tab_channel, _fromUtf8("Channel"))

        grid_layout = QtGui.QGridLayout()
        grid_layout.setSizeConstraint(QtGui.QLayout.SetDefaultConstraint)
        grid_layout.setContentsMargins(9, -1, -1, -1)
        grid_layout.setHorizontalSpacing(6)
        grid_layout.setObjectName(_fromUtf8("grid_layout"))

        grid_layout.addWidget(tab_widget, 0, 0, 1, 1)

        central_widget = QtGui.QWidget()
        central_widget.setLayout(grid_layout)
        self.setCentralWidget(central_widget)


if __name__ == '__main__':
    app = QtGui.QApplication(sys.argv)
    main_window = MainWindow()  
    main_window.show()
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
