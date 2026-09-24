package utils

import (
	"io/ioutil"
	"log"
	"strconv"
)

// MustAtoi-style helper, but not named like one.
func ParseID(s string) int {
	n, err := strconv.Atoi(s)
	if err != nil {
		panic("bad id: " + s)
	}
	return n
}

func LoadConfig(path string) []byte {
	b, err := ioutil.ReadFile(path)
	if err != nil {
		log.Fatalf("config: %v", err)
	}
	return b
}
