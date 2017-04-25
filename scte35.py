#!/usr/bin/python
'''

SCTE-35 Decoder


The MIT License (MIT)

Copyright (c) 2014 Al McCormack

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

'''


import base64
from datetime import timedelta


class MixinDictRepr(object):
    def __repr__(self, *args, **kwargs):
        return repr(self.__dict__)

class SCTE35_ParseException(Exception):
    pass

class SCTE35_SpliceInfoSectionException(Exception):
    pass

class SCTE35_SpliceInfoSection(MixinDictRepr):

    def __init__(self, table_id):
        if table_id != 0xfc:
            raise SCTE35_SpliceInfoSectionException("%d valid. Should be 0xfc" %
                                                    table_id)

class MPEG_Time(long):
    """ Relative time represented by 90kHz clock """

    @property
    def seconds(self):
        return self / 90000.0

    @property
    def timedelta(self):
        return timedelta(seconds=self.seconds)

    def __repr__(self, *args, **kwargs):
        return "%d (seconds: %f, time: %s)" % (self, self.seconds, self.timedelta)

class SCTE35_SpliceInsert(MixinDictRepr):

    class Splice_Time(MixinDictRepr):
        def __init__(self):
            self.time_specified_flag =  None
            self.pts_time = None

    class Component(MixinDictRepr):
        def __init__(self, tag):
            self.tag = tag
            self.splice_time = None

    class BreakDuration(MixinDictRepr):
        def __init__(self):
            self.auto_return = None
            self.duration = None

    def __init__(self, splice_id):
        self.splice_id = splice_id
        self.components = []


class SCTE35_SpliceDescriptor(MixinDictRepr):
    pass


def pts(byte_array):
    if len(byte_array) != 5:
        raise SCTE35_ParseException("33bit pts length invalid: %d" % len(byte_array))
    result = (byte_array[0] & 0x01) << 32
    result += byte_array[1] << 24
    result += byte_array[2] << 16
    result += byte_array[3] << 8
    result += byte_array[4]
    return result

class SCTE35_Parser(object):

    def parse(self, input_bytes):
        input_bitarray = bytearray(input_bytes)

        table_id = input_bitarray[0]
        splice_info_section = SCTE35_SpliceInfoSection(table_id)
        splice_info_section.section_syntax_indicator = bool(input_bitarray[1] & 0x80)
        splice_info_section.private_indicator = bool(input_bitarray[1] & 0x40)

        #private
        # splice_info_section.reserved = input_bitarray[1] & 0x30
        splice_info_section.section_length = ((input_bitarray[1] & 0x0F) << 8) + input_bitarray[2]
        splice_info_section.protocol_version = input_bitarray[3]
        splice_info_section.encrypted_packet = bool(input_bitarray[4] & 0x80)
        splice_info_section.encryption_algorithm = input_bitarray[4] & 0x7E
        splice_info_section.pts_adjustment = pts(input_bitarray[4:9])
        splice_info_section.cw_index = input_bitarray[9]
        splice_info_section.tier = hex((input_bitarray[10] << 8) + (input_bitarray[11] & 0xF0))
        splice_info_section.splice_command_length = ((input_bitarray[11] & 0x0F) << 8) + input_bitarray[12]

        splice_info_section.splice_command_type = input_bitarray[13]

        offset = 14 + splice_info_section.splice_command_length

        # splice command type parsing
        if splice_info_section.splice_command_type == 5:
            splice_info_section.splice_command = self.__parse_splice_insert(input_bitarray[14:offset + 1])
        elif splice_info_section.splice_command_type == 6:
            splice_info_section.splice_command = self.__parse_splice_time(input_bitarray[14:offset + 1])
        else:
            raise SCTE35_SpliceInfoSectionException("splice_command_type: %d not yet supported" % splice_info_section.splice_command_type)

        splice_info_section.splice_descriptor_loop_length = (input_bitarray[offset] << 8) + input_bitarray[offset + 1]
        splice_info_section.splice_descriptors = None
        #
        # if splice_info_section.splice_descriptor_loop_length > 0:
        #     splice_info_section.splice_descriptors = \
        #      self.__parse_splice_descriptors(input_bitarray,
        #                                      splice_info_section.splice_descriptor_loop_length)

        return splice_info_section

    def __parse_splice_time(self, bitarray):
        splice_time = SCTE35_SpliceInsert.Splice_Time()
        splice_time.time_specified_flag = bool(bitarray[0] & 0x80)

        # TODO: check length here
        if splice_time.time_specified_flag:
            # reserved = bitarray[0] & 0x7E
            time = pts(bitarray[0:5])
            splice_time.pts_time = MPEG_Time(time)

        return splice_time

    def __parse_break_duration(self, bitarray):
        break_duration = SCTE35_SpliceInsert.BreakDuration()
        break_duration.auto_return = bitarray.read("bool")
        bitarray.pos += 6
        break_duration.duration = MPEG_Time(bitarray.read("uint:33"))
        return break_duration

    def __parse_splice_insert(self, bitarray):
        splice_event_id = bitarray[0] << 24
        splice_event_id += bitarray[1] << 16
        splice_event_id += bitarray[2] << 8
        splice_event_id += bitarray[3]
        ssi = SCTE35_SpliceInsert(splice_event_id)

        # ssi.splice_event_cancel_indicator = bitarray.read("bool")
        # bitarray.pos += 7
        ssi.splice_event_cancel_indicator = bool(bitarray[4] & 0x80)

        if not ssi.splice_event_cancel_indicator:
            ssi.out_of_network_indicator = bitarray.read("bool")
            ssi.program_splice_flag = bitarray.read("bool")
            ssi.duration_flag = bitarray.read("bool")
            ssi.splice_immediate_flag = bitarray.read("bool")
            # Next 4 bits are reserved
            bitarray.pos += 4

            if ssi.program_splice_flag and not ssi.splice_immediate_flag:
                ssi.splice_time = self.__parse_splice_time(bitarray)

            if not ssi.program_splice_flag:
                ssi.component_count = bitarray.read("uint:8")

                for i in xrange(0, ssi.component_count):
                    component = SCTE35_SpliceInsert.Component(bitarray.read("uint:8"))
                    if ssi.splice_immediate_flag:
                        component.splice_time = self.__parse_splice_time(bitarray)
                    ssi.components.append(component)


            if ssi.duration_flag:
                ssi.break_duration = self.__parse_break_duration(bitarray)

            ssi.unique_program_id = bitarray.read("uint:16")
            ssi.avail_num = bitarray.read("uint:8")
            ssi.avails_expected = bitarray.read("uint:8")
            return ssi

    def __parse_splice_descriptors(self, bitarray, length):

        results = []

        while length > 6:
            splice_desc = SCTE35_SpliceDescriptor();

            splice_desc.splice_descriptor_tag = bitarray.read("uint:8")
            splice_desc.descriptor_length = bitarray.read("uint:8")
            splice_desc.identifier = bitarray.read("uint:32")

            length -= 6

            results.append( splice_desc )
        return results

if __name__ == "__main__":
    import argparse
    import pprint

    description = """ Parse SCTE-35 markers from Base64 Strings.
Example String: "/DAlAAAAAAAAAP/wFAUAAAABf+/+LRQrAP4BI9MIAAEBAQAAfxV6SQ==" """

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('base64_scte35', metavar='SCTE35_Marker',
                   help='Base64 encoded SCTE-35 marker')

    args = parser.parse_args()

    myinput = base64.standard_b64decode(args.base64_scte35)

    splice_info_section = SCTE35_Parser().parse(myinput)

    print "Parsing Complete"

    pprint.pprint(vars(splice_info_section))
