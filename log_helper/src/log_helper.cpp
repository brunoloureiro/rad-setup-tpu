#include "log_helper_base.h"
#include "log_helper_udp.h"
#include "log_helper.h"

#include <cstring>
#include <memory>

std::unique_ptr<log_helper::log_helper_base> log_helper_ptr;

void set_max_errors_iter(size_t max_errors) {
    //check if it is empty
    if (log_helper_ptr) {
        log_helper_ptr->set_max_errors_iter(max_errors);
    }
}

void set_max_infos_iter(size_t max_infos) {
    //check if it is empty
    if (log_helper_ptr) {
        log_helper_ptr->set_max_infos_iter(max_infos);
    }
}

void set_iter_interval_print(size_t interval) {
    //check if it is empty
    if (log_helper_ptr) {
        log_helper_ptr->set_iter_interval_print(interval);
    }
}

void disable_double_error_kill() {
    //check if it is empty
    if (log_helper_ptr) {
        return log_helper_ptr->disable_double_error_kill();
    }
}

void start_log_file(const char *benchmark_name, const char *test_info) {
    //TODO: do for local log file
    log_helper_ptr = std::make_unique<log_helper::log_helper_udp>(benchmark_name, test_info);
}

void end_log_file() {
    auto mem = log_helper_ptr.release();
    delete mem;
}

void start_iteration() {
    if (log_helper_ptr) {
        log_helper_ptr->start_iteration();
    }
}

void end_iteration() {
    if (log_helper_ptr) {
        log_helper_ptr->end_iteration();
    }
}

void log_error_count(size_t kernel_errors) {
    if (log_helper_ptr) {
        log_helper_ptr->log_error_count(kernel_errors);
    }
}

void log_info_count(size_t info_count) {
    if (log_helper_ptr) {
        log_helper_ptr->log_info_count(info_count);
    }
}

void log_error_detail(char *string) {
    std::string error_detail(string);
    if (log_helper_ptr) {
        log_helper_ptr->log_error_detail(error_detail);
    }
}

void log_info_detail(char *string) {
    std::string info_detail(string);
    if (log_helper_ptr) {
        log_helper_ptr->log_info_detail(info_detail);
    }
}
