import unittest

from family_activity.process_network import ProcessCounterAccumulator, parse_nettop_line


class ProcessNetworkTests(unittest.TestCase):
    def test_parses_only_process_name_and_requested_byte_columns(self):
        self.assertEqual(parse_nettop_line('Safari.123,4096,1024,'),
                         ('123', 'Safari', 4096, 1024))
        for line in (
            ',bytes_in,bytes_out,',
            'time,,interface,state,bytes_in,bytes_out',
            'Safari.123,NaN,1024,',
            'Safari.123,-1,1024,',
            'Safari,4096,1024,',
            'Safari.123,4096,1024,private.example',
        ):
            with self.subTest(line=line):
                self.assertIsNone(parse_nettop_line(line))

    def test_accumulates_cumulative_counters_without_persisting_process_ids(self):
        current = [1.0]
        sampler = ProcessCounterAccumulator(clock=lambda: current[0])
        self.assertTrue(sampler.observe_line('Safari.123,10000,2000,'))
        self.assertEqual(sampler.drain(), ())  # Initial totals are a baseline.
        current[0] += 1
        sampler.observe_line('Safari.123,10500,2150,')
        sampler.observe_line('Safari.234,100,50,')
        current[0] += 1
        sampler.observe_line('Safari.234,300,75,')
        self.assertEqual([(row.process, row.received, row.sent) for row in sampler.drain()],
                         [('Safari', 700, 175)])
        self.assertEqual(sampler.drain(), ())

    def test_counter_reset_and_stale_pid_start_a_new_baseline(self):
        current = [0.0]
        sampler = ProcessCounterAccumulator(clock=lambda: current[0], stale_after=10)
        sampler.observe_line('Browser.70,2000,500,')
        current[0] += 1
        sampler.observe_line('Browser.70,1,1,')
        current[0] += 1
        sampler.observe_line('Browser.70,101,21,')
        current[0] += 20
        sampler.observe_line('Browser.70,5000,800,')
        self.assertEqual([(row.process, row.received, row.sent) for row in sampler.drain()],
                         [('Browser', 100, 20)])


if __name__ == '__main__':
    unittest.main()
