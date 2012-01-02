'''
Created on 02.01.2012

@author: Kai
'''

from construct import Container, Enum, PrefixedArray, Struct, ULInt16, ULInt8, OptionalGreedyRepeater, CString, Switch

class InstantSoupData(object):
        
    ClientMemberShipOption = PrefixedArray(Struct("Server",
                                                  CString("ServerID"),
                                                  PrefixedArray(CString('Channels'),
                                                                ULInt8("NumChannels"))
                                                  ),
                                           ULInt8("NumServers"))

    ServerInviteOption = Struct("ServerInviteOption",
                                CString("ChannelID"),
                                PrefixedArray(CString("ClientID"),
                                              ULInt8("NumClients")))

    Option = Struct("Option",
                    Enum(ULInt8("OptionID"),
                         CLIENT_NICK_OPTION = 0x01,
                         CLIENT_MEMBERSHIP_OPTION = 0x02,
                         SERVER_OPTION = 0x10,
                         SERVER_CHANNELS_OPTION = 0x11,
                         SERVER_INVITE_OPTION = 0x12),
                    Switch("OptionData",
                           lambda ctx: ctx["OptionID"],
                           {
                                "CLIENT_NICK_OPTION"        : CString('Nickname'),
                                "CLIENT_MEMBERSHIP_OPTION"  : ClientMemberShipOption,
                                "SERVER_OPTION"             : Struct("ServerOption", ULInt16("Port")),
                                "SERVER_CHANNELS_OPTION"    : PrefixedArray(CString("Channels"), ULInt8("NumChannels")),
                                "SERVER_INVITE_OPTION"      : ServerInviteOption
                           }))

    peerPDU = Struct("peerPDU",
                     CString('ClientID'),
                     OptionalGreedyRepeater(Option))