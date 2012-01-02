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

from InstantSoupData import *

if __name__ == '__main__':
    data = InstantSoupData.peerPDU.build(Container(ClientID = "Bob",
                                                   Option = [Container(OptionID = "SERVER_INVITE_OPTION",
                                                                       OptionData = Container(ChannelID = "TM2011",
                                                                                              ClientID = ["Alice", "Billy"])),
                                                             Container(OptionID = "CLIENT_NICK_OPTION",
                                                                       OptionData = "Susan")]))

    print repr(data)
    packet = InstantSoupData.peerPDU.parse(data)
    print packet