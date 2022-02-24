#ifndef LOG_HELPER_H
#define LOG_HELPER_H

/**
 * for C++ compilers this macro must exists
 */
#ifdef __cplusplus

#include <cstdint>
#include <cstddef>

extern "C" {
#else
#include <stddef.h>
#include <stdint.h>
#endif

/**
 * Set the max errors that can be found for a single iteration
* If more than max errors is found, exit the program
 * @param max_errors
 * @return
 */
void set_max_errors_iter(size_t max_errors);

/**
 * Set the max number of infos logged in a single iteration
 */
void set_max_infos_iter(size_t max_infos);

/**
 *  Set the interval the program must print log details,
 *  default is 1 (each iteration)
 * @param interval
 * @return
 */
void set_iter_interval_print(size_t interval);

/**
 * Disable double error kill
 * this will disable double error kill if
 * two errors happened sequentially
 */
void disable_double_error_kill();

/**
 * Generate the log file name, log info from user about the test
 * to be executed and reset log variables
 * @param benchmark_name
 * @param test_info
 * @return bool as uint8_t
 */
void start_log_file(const char *benchmark_name, const char *test_info);

/**
 * Log the string "#END" and reset global variables
 * @return bool as uint8_t
 */
void end_log_file();

/**
 *  Start time to measure kernel time, also update
 *  iteration number and log to file
 * @return bool as uint8_t
 */
void start_iteration();

/**
 * Finish the measured kernel time log both
 * time (total time and kernel time)
 * @return bool as uint8_t
 */
void end_iteration();

/**
 * Update total errors variable and log both
 * errors(total errors and kernel errors)
 * @param kernel_errors
 * @return bool as uint8_t
 */
void log_error_count(size_t kernel_errors);

/**
 * Update total infos variable and log both infos(total infos and iteration infos)
 * @param info_count
 * @return bool as uint8_t
 */
void log_info_count(size_t info_count);

/**
 * Print some string with the detail of an error to log file
 * @param string
 * @return bool as uint8_t
 */
void log_error_detail(char *string);

/**
 * Print some string with the detail of an error/information to log file
 * @param string
 * @return bool as uint8_t
 */
void log_info_detail(char *string);

//end C++ macro section
#ifdef __cplusplus
}
#endif

#endif //LOG_HELPER_H
