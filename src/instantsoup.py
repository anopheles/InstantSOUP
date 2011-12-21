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

from construct import Container, Enum, PrefixedArray, Struct, ULInt16, ULInt8, OptionalGreedyRepeater, CString, Switch

ClientMemberShipOption = PrefixedArray(
                        Struct(
                            "Server",
                            CString("ServerID"),
                            PrefixedArray(CString('Channels'), ULInt8("NumChannels"))
                        ),
                        ULInt8("NumServers")
)


ServerInviteOption = Struct(
                    "ServerInviteOption",
                    CString("ChannelID"),
                    PrefixedArray(CString("ClientID"), ULInt8("NumClients"))
)


Option = Struct(
        'Option',
        Enum(
            ULInt8('OptionID'),
            CLIENT_NICK_OPTION = 0x01,
            CLIENT_MEMBERSHIP_OPTION = 0x02,
            SERVER_OPTION = 0x10,
            SERVER_CHANNELS_OPTION = 0x11,
            SERVER_INVITE_OPTION = 0x12
        ),
        Switch("OptionData", lambda ctx: ctx["OptionID"],
            {
                "CLIENT_NICK_OPTION" : CString('Nickname'),
                "CLIENT_MEMBERSHIP_OPTION" : ClientMemberShipOption,
                "SERVER_OPTION" : Struct("ServerOption", ULInt16('Port')),
                "SERVER_CHANNELS_OPTION" : PrefixedArray(CString('Channels'), ULInt8("NumChannels")),
                "SERVER_INVITE_OPTION" : ServerInviteOption
            }
        )
)


peerPDU = Struct(
          'peerPDU',
          CString('ClientID'),
          OptionalGreedyRepeater(Option)
)


if __name__ == '__main__':
    data = peerPDU.build(Container(ClientID="Bob", Option=[
                                                    Container(OptionID="SERVER_INVITE_OPTION", OptionData=Container(ChannelID="TM2011", ClientID=["Alice", "Billy"])),
                                                    Container(OptionID="CLIENT_NICK_OPTION", OptionData="Susan")]
                                  )
    )

    print repr(data)
    packet = peerPDU.parse(data)
    print packet